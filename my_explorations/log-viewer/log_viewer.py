#!/usr/bin/env python3
"""Desk-bot live log viewer (standalone).

Aggregates host-side log sources -- docker containers and log files -- and
streams them to a browser over a websocket, so one page shows the whole stack:

    bot (xiaozhi-server) + manager-api + digital-human runtime

Run:
    python3 log_viewer.py --port 8007
    open http://127.0.0.1:8007/logs.html

Sources live in ``sources.json`` next to this file (see README.md). Stdlib only:
no venv, no third-party dependencies. This tool only *reads* logs; it is not
part of the backend stack and not part of digital-human.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TextIO
from urllib.parse import urlparse

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
DEFAULT_CONFIG = APP_DIR / "sources.json"
DEFAULT_HISTORY = 200
DEFAULT_PORT = 8007

# Photos saved by the server land in the container's tmp/ (bind-mounted to
# deploy/logs). Serve them next to the log page so a PHOTO line can show the
# exact frame the model received.
PHOTO_ROOT = Path(
    os.environ.get(
        "XIAOZHI_PHOTO_DIR",
        REPO_ROOT / "my_explorations" / "server" / "deploy" / "logs" / "photos",
    )
)
PHOTO_RE = re.compile(r"(/photos/[0-9A-Za-z._/-]+\.(?:jpe?g|png))", re.IGNORECASE)

LEVEL_TOKENS = (
    ("error", ("-ERROR-", " - ERROR - ", "[ERROR]", "ERROR:", "] ERROR ")),
    ("warn", ("-WARNING-", "-WARN-", " - WARNING - ", "[WARNING]", "WARN:", "] WARNING ", "] WARN ")),
    ("debug", ("-DEBUG-", " - DEBUG - ", "[DEBUG]", "] DEBUG ")),
)

# docker/java log lines are full of ANSI colour codes; drop them before display,
# level detection, session extraction and recording.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
ANSI_OSC_RE = re.compile(r"\x1b\][^\x07]*\x07")

DEFAULT_RECORD = {
    "enabled": False,
    "dir": "logs",
    "retention_days": 14,
    "max_file_mb": 64,
    "replay_recent": 200,
}


@dataclass(frozen=True)
class SessionRule:
    """How to recognise sessions in one source's lines.

    All patterns are applied with ``re.search``; capture group 1 is the value.
    ``id`` starts/continues a session, ``end`` closes it, ``device`` attaches a
    device label (e.g. a MAC) to the current session. With ``sticky`` the
    session/device stays attached to every following line of that source until
    ``end`` matches.
    """

    id_pattern: re.Pattern[str] | None = None
    end_pattern: re.Pattern[str] | None = None
    device_pattern: re.Pattern[str] | None = None
    sticky: bool = True


@dataclass(frozen=True)
class SourceSpec:
    """One log source: a docker container or a file on the host."""

    name: str
    kind: str  # "docker" | "file"
    target: str
    label: str = ""
    tail: int = 20
    session: SessionRule | None = None

    @property
    def display(self) -> str:
        return self.label or self.name


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_sources(
    config_path: Path, history_override: int | None = None
) -> tuple[list[SourceSpec], int, dict]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"config not found: {config_path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {config_path}: {exc}")

    if isinstance(raw, list):
        entries = raw
        history = DEFAULT_HISTORY
        record_raw: dict = {}
    else:
        entries = raw.get("sources") or []
        history = int(raw.get("history", DEFAULT_HISTORY))
        record_raw = raw.get("record") or {}

    if history_override is not None:
        history = history_override

    record = dict(DEFAULT_RECORD)
    if isinstance(record_raw, bool):
        record["enabled"] = record_raw
    elif isinstance(record_raw, dict):
        record.update(record_raw)
    elif record_raw:
        raise SystemExit("'record' must be an object or a boolean")
    record["enabled"] = bool(record.get("enabled", False))
    record["retention_days"] = max(int(record.get("retention_days", 14)), 1)
    record["max_file_mb"] = max(int(record.get("max_file_mb", 64)), 1)
    record["replay_recent"] = max(int(record.get("replay_recent", 200)), 0)
    record["dir"] = str(record.get("dir") or "logs")

    sources: list[SourceSpec] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SystemExit(f"sources[{index}] must be an object")
        if not entry.get("enabled", True):
            continue

        name = str(entry.get("name", "")).strip()
        kind = str(entry.get("kind", "")).strip().lower()
        target = str(entry.get("target", "")).strip()

        if not name:
            raise SystemExit(f"sources[{index}]: missing 'name'")
        if name in seen:
            raise SystemExit(f"sources[{index}]: duplicate name '{name}'")
        if kind not in ("docker", "file"):
            raise SystemExit(f"sources[{index}] ('{name}'): kind must be 'docker' or 'file'")
        if not target:
            raise SystemExit(f"sources[{index}] ('{name}'): missing 'target'")

        if kind == "file":
            target = _resolve_path(target)

        seen.add(name)
        sources.append(
            SourceSpec(
                name=name,
                kind=kind,
                target=target,
                label=str(entry.get("label", "")).strip(),
                tail=max(int(entry.get("tail", 20)), 0),
                session=_parse_session_rule(entry.get("session"), index, name),
            )
        )

    if not sources:
        raise SystemExit(f"no enabled sources in {config_path}")
    return sources, max(int(history), 10), record


def _parse_session_rule(raw: object, index: int, name: str) -> SessionRule | None:
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise SystemExit(f"sources[{index}] ('{name}'): 'session' must be an object")

    def compile_pattern(key: str, need_group: bool) -> re.Pattern[str] | None:
        pattern = raw.get(key)
        if not pattern:
            return None
        try:
            compiled = re.compile(str(pattern))
        except re.error as exc:
            raise SystemExit(
                f"sources[{index}] ('{name}'): invalid session.{key} regex: {exc}"
            )
        if need_group and compiled.groups < 1:
            raise SystemExit(
                f"sources[{index}] ('{name}'): session.{key} needs one capture group"
            )
        return compiled

    rule = SessionRule(
        id_pattern=compile_pattern("id", True),
        end_pattern=compile_pattern("end", False),
        device_pattern=compile_pattern("device", True),
        sticky=bool(raw.get("sticky", True)),
    )
    if rule.id_pattern is None and rule.device_pattern is None:
        raise SystemExit(
            f"sources[{index}] ('{name}'): session needs 'id' or 'device'"
        )
    return rule


def _resolve_path(target: str) -> str:
    """Resolve a file target: absolute, ~, or relative to the repo root."""
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path.resolve())


# --------------------------------------------------------------------------- #
# recording
# --------------------------------------------------------------------------- #
class LogRecorder:
    """Append every published frame to ``<dir>/<YYYY-MM-DD>/<source>.jsonl``.

    One JSON object per line, byte-for-byte the same frame the browser gets, so
    recordings are replayable and greppable::

        jq -c 'select(.session=="<id>")' logs/2026-11-13/server.jsonl

    Files rotate on size (``max_file_mb``) and directories older than
    ``retention_days`` are pruned, so this cannot grow without bound.
    """

    def __init__(
        self,
        directory: Path,
        retention_days: int = 14,
        max_file_mb: int = 64,
    ) -> None:
        self.dir = Path(directory).expanduser().resolve()
        self.retention_days = retention_days
        self.max_bytes = max_file_mb * 1024 * 1024
        self._lock = threading.Lock()
        self._handles: dict[tuple[str, str], TextIO] = {}
        self._written: dict[tuple[str, str], int] = {}
        self._last_prune = 0.0
        self.dir.mkdir(parents=True, exist_ok=True)
        self.prune()

    # ---- writing ----
    def write(self, source: str, payload: str) -> None:
        now = time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        day_dir = self.dir / day

        with self._lock:
            if now - self._last_prune > 3600:
                self.prune_locked()

            key = (day, source)
            try:
                day_dir.mkdir(parents=True, exist_ok=True)
                handle = self._handles.get(key)
                if handle is None or handle.closed:
                    path = day_dir / f"{source}.jsonl"
                    handle = path.open("a", encoding="utf-8", buffering=1)
                    self._handles[key] = handle
                    self._written[key] = path.stat().st_size
                handle.write(payload + "\n")
                self._written[key] = self._written.get(key, 0) + len(payload) + 1
                if self._written[key] >= self.max_bytes:
                    self._rotate_locked(key, handle)
            except OSError:
                # never let a disk problem kill the live tail
                self._handles.pop(key, None)
                self._written.pop(key, None)

    def _rotate_locked(self, key: tuple[str, str], handle: TextIO) -> None:
        day, source = key
        try:
            handle.close()
        except OSError:
            pass
        stamp = time.strftime("%H%M%S")
        path = self.dir / day / f"{source}.jsonl"
        target = self.dir / day / f"{source}.{stamp}.jsonl"
        suffix = 1
        while target.exists():
            target = self.dir / day / f"{source}.{stamp}-{suffix}.jsonl"
            suffix += 1
        if path.exists():
            os.replace(path, target)
        self._handles.pop(key, None)
        self._written.pop(key, None)

    def close(self) -> None:
        with self._lock:
            for handle in self._handles.values():
                try:
                    handle.close()
                except OSError:
                    pass
            self._handles.clear()
            self._written.clear()

    # ---- retention ----
    def prune(self) -> None:
        with self._lock:
            self.prune_locked()

    def prune_locked(self) -> None:
        self._last_prune = time.time()
        cutoff = time.time() - self.retention_days * 86400
        try:
            entries = list(self.dir.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir():
                continue
            try:
                day_ts = time.mktime(time.strptime(entry.name, "%Y-%m-%d"))
            except ValueError:
                continue
            if day_ts + 86400 < cutoff:
                shutil.rmtree(entry, ignore_errors=True)

    # ---- reading back ----
    def replay(self, limit: int) -> list[str]:
        """Return up to ``limit`` recorded frames (today first, then older)."""
        if limit <= 0:
            return []
        try:
            entries = list(self.dir.iterdir())
        except OSError:
            return []
        days = sorted(
            (p for p in entries if p.is_dir() and _is_day_dir(p.name)),
            reverse=True,
        )
        frames: list[tuple[float, str]] = []
        for day_dir in days:
            for path in sorted(day_dir.glob("*.jsonl")):
                for line in _tail_lines(path, limit):
                    frames.append((_frame_ts(line), line))
                if len(frames) >= limit * 2:
                    break
            if len(frames) >= limit * 2:
                break
        frames.sort(key=lambda item: item[0])
        return [line for _, line in frames[-limit:]]

    def stats(self) -> list[dict]:
        out: list[dict] = []
        try:
            days = sorted(
                (p for p in self.dir.iterdir() if p.is_dir() and _is_day_dir(p.name)),
                reverse=True,
            )
        except OSError:
            return out
        for day_dir in days[:30]:
            files = []
            for path in sorted(day_dir.glob("*.jsonl")):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                files.append(
                    {
                        "file": path.name,
                        "source": path.name.split(".", 1)[0],
                        "bytes": stat.st_size,
                        "modified": round(stat.st_mtime, 3),
                    }
                )
            out.append({"date": day_dir.name, "files": files})
        return out


def _is_day_dir(name: str) -> bool:
    try:
        time.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _frame_ts(line: str) -> float:
    try:
        frame = json.loads(line)
    except (ValueError, TypeError):
        return 0.0
    if not isinstance(frame, dict):
        return 0.0
    try:
        return float(frame.get("ts") or 0)
    except (ValueError, TypeError):
        return 0.0


def _tail_lines(path: Path, limit: int, max_bytes: int = 512 * 1024) -> list[str]:
    """Read the last ``limit`` lines of a file without loading the whole thing."""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            start = max(0, size - max_bytes)
            handle.seek(start)
            data = handle.read()
    except OSError:
        return []

    raw_lines = data.splitlines()
    if start > 0 and raw_lines:
        raw_lines = raw_lines[1:]  # first line is probably cut in half
    lines: list[str] = []
    for raw in raw_lines[-limit:]:
        try:
            lines.append(raw.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    return lines


def _clean_line(line: str) -> str:
    """Drop ANSI colour/OSC sequences and trailing CR/LF."""
    return ANSI_OSC_RE.sub("", ANSI_RE.sub("", line)).rstrip("\r\n")


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #
class _SessionTracker:
    __slots__ = ("lock", "session", "device")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.session: str | None = None
        self.device: str | None = None


class LogStreamer:
    """Tails every source and fans frames out to websocket subscribers."""

    def __init__(
        self,
        sources: list[SourceSpec],
        history: int = DEFAULT_HISTORY,
        recorder: LogRecorder | None = None,
        replay_recent: int = 0,
    ) -> None:
        self.sources = list(sources)
        self.history = history
        self.recorder = recorder
        self._subscribers: list[queue.Queue[str]] = []
        self._recent: list[str] = []
        self._lock = threading.Lock()
        self._running = False
        self._started = False
        self._trackers: dict[str, _SessionTracker] = {
            src.name: _SessionTracker() for src in self.sources if src.session
        }
        self._rules: dict[str, SessionRule] = {
            src.name: src.session for src in self.sources if src.session
        }
        self._session_meta: dict[str, dict] = {}
        self._status: dict[str, dict] = {
            src.name: {"connected": False, "lines": 0, "lastLineAt": None, "note": ""}
            for src in self.sources
        }

        if recorder is not None and replay_recent > 0:
            self._recent = recorder.replay(min(replay_recent, history))
            for payload in self._recent:
                self._note_session(payload)

    # ---- lifecycle ----
    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            self._running = True

        for src in self.sources:
            target = self._run_docker if src.kind == "docker" else self._run_file
            threading.Thread(
                target=target,
                args=(src,),
                name=f"logstream-{src.name}",
                daemon=True,
            ).start()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def is_running(self) -> bool:
        return self._running

    # ---- subscribers ----
    def subscribe(self) -> queue.Queue[str]:
        client_queue: queue.Queue[str] = queue.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.append(client_queue)
        return client_queue

    def unsubscribe(self, client_queue: queue.Queue[str]) -> None:
        with self._lock:
            if client_queue in self._subscribers:
                self._subscribers.remove(client_queue)

    def recent(self, limit: int | None = None) -> list[str]:
        with self._lock:
            return self._recent[-limit:] if limit else list(self._recent)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "name": src.name,
                    "label": src.display,
                    "kind": src.kind,
                    "target": src.target,
                    "sessions": bool(src.session),
                    **self._status[src.name],
                }
                for src in self.sources
            ]

    def sessions(self) -> list[dict]:
        with self._lock:
            return sorted(
                (dict(meta) for meta in self._session_meta.values()),
                key=lambda meta: meta.get("last") or 0,
                reverse=True,
            )

    def recording_info(self) -> dict:
        if self.recorder is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "dir": str(self.recorder.dir),
            "retention_days": self.recorder.retention_days,
            "max_file_mb": self.recorder.max_bytes // (1024 * 1024),
        }

    # ---- session annotation ----
    def _annotate(self, name: str, line: str) -> tuple[str | None, str | None]:
        """Attach the current session/device to a line, updating sticky state."""
        src_rule = self._rules.get(name)
        tracker = self._trackers.get(name)
        if src_rule is None or tracker is None:
            return None, None

        with tracker.lock:
            id_match = src_rule.id_pattern.search(line) if src_rule.id_pattern else None
            device_match = (
                src_rule.device_pattern.search(line) if src_rule.device_pattern else None
            )
            end_match = src_rule.end_pattern.search(line) if src_rule.end_pattern else None

            if device_match:
                tracker.device = device_match.group(1).strip()
            if id_match:
                tracker.session = id_match.group(1).strip()

            session = tracker.session if (id_match or src_rule.sticky) else None
            device = tracker.device if (device_match or src_rule.sticky) else None

            if end_match and not id_match:
                tracker.session = None
                tracker.device = None

            return session, device

    def _note_session(self, payload: str) -> None:
        try:
            frame = json.loads(payload)
        except (ValueError, TypeError):
            return
        if not isinstance(frame, dict):
            return
        session = frame.get("session")
        if not session:
            return
        with self._lock:
            meta = self._session_meta.get(session)
            if meta is None:
                meta = {
                    "id": session,
                    "source": frame.get("source"),
                    "device": frame.get("device"),
                    "first": frame.get("ts"),
                    "last": frame.get("ts"),
                    "count": 0,
                }
                self._session_meta[session] = meta
                if len(self._session_meta) > 200:
                    oldest = min(
                        self._session_meta.values(), key=lambda m: m.get("last") or 0
                    )
                    self._session_meta.pop(oldest["id"], None)
            meta["last"] = frame.get("ts")
            meta["count"] += 1
            if frame.get("device"):
                meta["device"] = frame["device"]

    # ---- publish ----
    def _publish(self, name: str, level: str, line: str) -> None:
        line = _clean_line(line)
        if not line:
            return

        session, device = self._annotate(name, line)
        frame = {"source": name, "level": level, "line": line, "ts": round(time.time(), 3)}
        if session:
            frame["session"] = session
        if device:
            frame["device"] = device
        photo = PHOTO_RE.search(line)
        if photo:
            frame["photo"] = photo.group(1)
        payload = json.dumps(frame, ensure_ascii=False)

        with self._lock:
            self._recent.append(payload)
            if len(self._recent) > self.history:
                del self._recent[: len(self._recent) - self.history]
            subscribers = list(self._subscribers)
            status = self._status.get(name)
            if status is not None:
                status["lines"] += 1
                status["lastLineAt"] = frame["ts"]

        if session:
            self._note_session(payload)
        if self.recorder is not None:
            self.recorder.write(name, payload)

        for client_queue in subscribers:
            try:
                client_queue.put_nowait(payload)
            except queue.Full:
                # slow client: drop its oldest frame instead of blocking the tail
                try:
                    client_queue.get_nowait()
                    client_queue.put_nowait(payload)
                except (queue.Empty, queue.Full):
                    pass

    def _set_status(self, name: str, **fields) -> None:
        with self._lock:
            self._status[name].update(fields)

    @staticmethod
    def _detect_level(line: str) -> str:
        upper = line.upper()
        for level, tokens in LEVEL_TOKENS:
            if any(token in upper for token in tokens):
                return level
        return "info"

    def _sleep(self, seconds: float) -> None:
        """Sleep in small slices so stop() is responsive."""
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            time.sleep(0.1)

    # ---- docker source ----
    def _run_docker(self, src: SourceSpec) -> None:
        if not shutil.which("docker"):
            self._set_status(src.name, connected=False, note="docker CLI 未找到")
            self._publish(src.name, "error", "[logs] 找不到 docker 命令, 无法读取容器日志")
            return

        since: float | None = None
        while self._running:
            cmd = ["docker", "logs", "-f", "--tail", str(src.tail)]
            if since is not None:
                # reconnect without re-printing lines we already forwarded
                cmd += ["--since", str(int(since))]
            cmd.append(src.target)

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError:
                self._publish(src.name, "error", "[logs] 找不到 docker 命令, 无法读取容器日志")
                return
            except Exception as exc:
                self._set_status(src.name, connected=False, note=str(exc))
                self._publish(src.name, "error", f"[logs] 启动 docker logs 失败: {exc}")
                self._sleep(5)
                continue

            self._set_status(src.name, connected=True, note=f"docker logs {src.target}")
            self._publish(src.name, "info", f"[logs] 已连接 docker logs {src.target}")

            try:
                for raw_line in proc.stdout:  # type: ignore[union-attr]
                    if not self._running:
                        proc.terminate()
                        break
                    line = _clean_line(raw_line)
                    if line:
                        since = time.time()
                        self._publish(src.name, self._detect_level(line), line)
                proc.wait()
            finally:
                if proc.poll() is None:
                    proc.terminate()

            if not self._running:
                break

            # 容器日志流断了(通常是容器重启), 上一轮的会话不再有效
            self._reset_session(src.name)
            self._set_status(src.name, connected=False, note="docker logs 已断开, 重连中")
            if proc.returncode == 0:
                self._publish(src.name, "warn", f"[logs] docker logs 结束 (容器已停止?), 5s 后重连 {src.target}")
                self._sleep(5)
            else:
                self._publish(
                    src.name,
                    "error",
                    f"[logs] docker logs 退出 (code {proc.returncode}); "
                    f"容器可能未运行: {src.target}, 10s 后重连",
                )
                self._sleep(10)

    # ---- file source ----
    def _run_file(self, src: SourceSpec) -> None:
        path = Path(src.target)
        start_at_end = True  # don't replay an old session on first attach
        missing_reported = False

        while self._running:
            try:
                handle = path.open("r", encoding="utf-8", errors="replace")
            except FileNotFoundError:
                if not missing_reported:
                    self._publish(src.name, "warn", f"[logs] 日志文件不存在: {path} (等待创建)")
                    missing_reported = True
                self._set_status(src.name, connected=False, note="文件不存在")
                self._sleep(2)
                continue
            except Exception as exc:
                self._set_status(src.name, connected=False, note=str(exc))
                self._publish(src.name, "error", f"[logs] 打开日志文件失败: {exc}")
                self._sleep(5)
                continue

            missing_reported = False
            rotated = False
            with handle:
                inode = _inode(path)
                if start_at_end:
                    handle.seek(0, os.SEEK_END)
                self._set_status(src.name, connected=True, note=str(path))
                self._publish(src.name, "info", f"[logs] 已连接文件 {path}")

                while self._running:
                    line = handle.readline()
                    if line:
                        line = _clean_line(line)
                        self._publish(src.name, self._detect_level(line), line)
                        continue

                    self._sleep(0.2)
                    try:
                        stat = path.stat()
                    except FileNotFoundError:
                        rotated = True
                        break
                    if stat.st_ino != inode or stat.st_size < handle.tell():
                        rotated = True  # replaced (copytruncate / rename+create)
                        break

            if rotated:
                start_at_end = False  # new file: read it from the beginning
                self._reset_session(src.name)
                self._publish(src.name, "info", f"[logs] 文件已轮转/截断, 重新打开 {path}")
                self._sleep(0.3)

    # ---- shutdown ----
    def shutdown(self) -> None:
        self.stop()
        with self._lock:
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for client_queue in subscribers:
            try:
                client_queue.put_nowait("__shutdown__")
            except queue.Full:
                pass
        if self.recorder is not None:
            self.recorder.close()

    def _reset_session(self, name: str) -> None:
        tracker = self._trackers.get(name)
        if tracker is None:
            return
        with tracker.lock:
            tracker.session = None
            tracker.device = None


def _inode(path: Path) -> int | None:
    try:
        return path.stat().st_ino
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# http + websocket
# --------------------------------------------------------------------------- #
class LogViewerHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, streamer: LogStreamer, **kwargs) -> None:
        self.streamer = streamer
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        if path == "/logs-ws":
            self._handle_logs_websocket()
            return

        if path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "sources": [src["name"] for src in self.streamer.snapshot()],
                    "recording": self.streamer.recording_info(),
                }
            )
            return

        if path == "/api/sources":
            self._send_json(
                {
                    "sources": self.streamer.snapshot(),
                    "sessions": self.streamer.sessions(),
                    "recording": self.streamer.recording_info(),
                }
            )
            return

        if path == "/api/recordings":
            self._send_recordings_index()
            return

        if path.startswith("/api/recordings/"):
            self._send_recording(path)
            return

        if path.startswith("/photos/"):
            self._send_photo(path)
            return

        if path in ("/", "/index.html"):
            self.path = "/logs.html"

        super().do_GET()

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_photo(self, url_path: str) -> None:
        rel = url_path[len("/photos/") :]
        try:
            root = PHOTO_ROOT.resolve()
            target = (root / rel).resolve()
            target.relative_to(root)
        except (ValueError, OSError):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = target.read_bytes()
        ctype = "image/png" if target.suffix.lower() == ".png" else "image/jpeg"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- recordings ----
    def _send_recordings_index(self) -> None:
        recorder = self.streamer.recorder
        if recorder is None:
            self._send_json({"enabled": False, "dir": None, "days": []})
            return
        self._send_json(
            {
                "enabled": True,
                "dir": str(recorder.dir),
                "retention_days": recorder.retention_days,
                "days": recorder.stats(),
            }
        )

    def _send_recording(self, path: str) -> None:
        # /api/recordings/<YYYY-MM-DD>/<source>[?limit=N&session=<id>]
        recorder = self.streamer.recorder
        parts = [part for part in path.split("/") if part]
        if recorder is None or len(parts) != 4:
            self.send_error(HTTPStatus.NOT_FOUND, "no recording")
            return

        _, _, day, source = parts
        if not _is_day_dir(day) or not re.fullmatch(r"[A-Za-z0-9_-]+", source):
            self.send_error(HTTPStatus.BAD_REQUEST, "bad date or source")
            return
        if source not in {src.name for src in self.streamer.sources}:
            self.send_error(HTTPStatus.NOT_FOUND, "unknown source")
            return

        query = dict(
            pair.split("=", 1)
            for pair in (urlparse(self.path).query or "").split("&")
            if "=" in pair
        )
        try:
            limit = max(int(query.get("limit", "2000") or 2000), 1)
        except ValueError:
            limit = 2000
        wanted = query.get("session", "").strip()

        files = sorted(
            file
            for file in (recorder.dir / day).glob(f"{source}*.jsonl")
            if file.name == f"{source}.jsonl" or file.name.startswith(f"{source}.")
        )
        lines: list[str] = []
        for file in files:
            lines.extend(_tail_lines(file, limit))
        if wanted:
            kept = []
            for line in lines:
                try:
                    frame = json.loads(line)
                except ValueError:
                    continue
                if wanted == "__none__":
                    if not frame.get("session"):
                        kept.append(line)
                elif frame.get("session") == wanted:
                    kept.append(line)
            lines = kept
        self._send_text("\n".join(lines[-limit:]) + ("\n" if lines else ""), "application/x-ndjson")

    # ---- websocket plumbing ----
    def _handle_logs_websocket(self) -> None:
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self.send_error(HTTPStatus.BAD_REQUEST, "expected websocket upgrade")
            return

        websocket_key = self.headers.get("Sec-WebSocket-Key")
        if not websocket_key:
            self.send_error(HTTPStatus.BAD_REQUEST, "missing Sec-WebSocket-Key")
            return

        accept_source = websocket_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept_value = base64.b64encode(
            hashlib.sha1(accept_source.encode("utf-8")).digest()
        ).decode("ascii")

        client_queue = self.streamer.subscribe()
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_value)
        self.end_headers()

        try:
            self.connection.settimeout(0.2)

            recent_frames = self.streamer.recent(200)
            hello = json.dumps(
                {
                    "type": "logs_hello",
                    "payload": {
                        "sources": self.streamer.snapshot(),
                        "history": len(recent_frames),
                        "sessions": self.streamer.sessions(),
                        "recording": self.streamer.recording_info(),
                    },
                },
                ensure_ascii=False,
            )
            self._send_websocket_text(hello)
            for frame in recent_frames:
                self._send_websocket_text(frame)

            while True:
                # drain (and ignore) client messages, mostly to notice close
                self._receive_websocket_message()

                try:
                    message = client_queue.get(timeout=0.2)
                    if message == "__shutdown__":
                        break
                    self._send_websocket_text(message)
                except queue.Empty:
                    if not self.streamer.is_running():
                        break
                    continue
        except socket.timeout:
            pass
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.streamer.unsubscribe(client_queue)

    def _receive_websocket_message(self) -> str | None:
        try:
            header = self._read_exact(2)
        except socket.timeout:
            return None

        if not header:
            return None

        first_byte, second_byte = header[0], header[1]
        opcode = first_byte & 0x0F
        masked = (second_byte & 0x80) != 0
        payload_length = second_byte & 0x7F

        if payload_length == 126:
            payload_length = int.from_bytes(self._read_exact(2), "big")
        elif payload_length == 127:
            payload_length = int.from_bytes(self._read_exact(8), "big")

        masking_key = self._read_exact(4) if masked else b""
        payload = self._read_exact(payload_length) if payload_length else b""

        if masked and payload:
            payload = bytes(
                byte ^ masking_key[index % 4]
                for index, byte in enumerate(payload)
            )

        if opcode == 0x8:
            raise ConnectionAbortedError("websocket closed by client")

        if opcode == 0x9:
            self._send_websocket_frame(0xA, payload)
            return None

        if opcode == 0xA:
            return None

        if opcode != 0x1:
            return None

        return payload.decode("utf-8", errors="replace")

    def _read_exact(self, size: int) -> bytes:
        if size <= 0:
            return b""

        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.connection.recv(size - len(chunks))
            if not chunk:
                raise ConnectionResetError("websocket connection closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_websocket_text(self, message: str) -> None:
        self._send_websocket_frame(0x1, message.encode("utf-8"))

    def _send_websocket_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray()
        header.append(0x80 | opcode)

        payload_length = len(payload)
        if payload_length < 126:
            header.append(payload_length)
        elif payload_length < 65536:
            header.append(126)
            header.extend(payload_length.to_bytes(2, "big"))
        else:
            header.append(127)
            header.extend(payload_length.to_bytes(8, "big"))

        self.wfile.write(bytes(header) + payload)
        self.wfile.flush()


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Standalone live-log viewer for the desk-bot stack.",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="sources config (default: sources.json next to this script)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"bind port (default: {DEFAULT_PORT})")
    parser.add_argument("--history", type=int, default=None, help="replay buffer size in frames")
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="disable writing frames to disk (overrides sources.json)",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="print resolved sources and exit",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()

    sources, history, record = load_sources(config_path, args.history)
    if args.no_record:
        record["enabled"] = False

    if args.list_sources:
        print(f"config: {config_path}  (history={history})")
        for src in sources:
            marks = []
            if src.session:
                marks.append("session")
            print(
                f"  {src.name:10s} {src.kind:7s} {src.target}  [{src.display}]"
                + (f"  ({', '.join(marks)})" if marks else "")
            )
        print(f"record: {'on' if record['enabled'] else 'off'}  dir={record['dir']}")
        return 0

    recorder: LogRecorder | None = None
    if record["enabled"]:
        record_dir = Path(record["dir"]).expanduser()
        if not record_dir.is_absolute():
            record_dir = APP_DIR / record_dir
        recorder = LogRecorder(
            record_dir,
            retention_days=record["retention_days"],
            max_file_mb=record["max_file_mb"],
        )

    streamer = LogStreamer(
        sources,
        history=history,
        recorder=recorder,
        replay_recent=record["replay_recent"] if recorder else 0,
    )
    handler = partial(LogViewerHandler, streamer=streamer)

    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        print(f"cannot listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    server.daemon_threads = True

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"log viewer : http://{shown_host}:{args.port}/logs.html", flush=True)
    print(f"log stream : ws://{shown_host}:{args.port}/logs-ws", flush=True)
    print(f"sources    : {', '.join(f'{s.name}({s.kind})' for s in sources)}", flush=True)
    if recorder is not None:
        print(
            f"recording  : {recorder.dir} (keep {record['retention_days']}d, "
            f"rotate {record['max_file_mb']}MB)",
            flush=True,
        )
    else:
        print("recording  : off", flush=True)
    print("press Ctrl+C to stop", flush=True)

    streamer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping log viewer")
    finally:
        streamer.shutdown()
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
