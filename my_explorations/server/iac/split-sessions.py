#!/usr/bin/env python3
"""Split the append-only xiaozhi-server log into per-session directories.

`deploy/logs/server.log` is the raw source of truth. This script never changes
it; it builds a disposable, deterministic view next to it:

    sessions/
      index.md                        human index (start here)
      index.jsonl                     one JSON record per session
      .generated.json                 rebuild marker + source statistics
      <start-date>/<start-time>_<short-id>/
        session.log                   raw lines, header comments at the top
        meta.json                     same fields as index.jsonl + artifacts
        photos/<date>/<file>          hardlinked (or copied) originals
      _global/<date>.log              startup / stop / unattributed lines
      _unassigned/photos/<date>/<file>

Every line of server.log ends up in exactly one place. Re-run the script after
the log grows; it rebuilds atomically from scratch (a full pass over a few MB
is cheap and avoids stale incremental state).

Session rules (same idea as log-viewer):

* a line with a non-empty `"session_id":"<uuid>"` starts/continues a session
* `"session_id":""` is ignored (MCP messages use it)
* session lines are sticky: VAD/ASR/LLM/TTS/provider lines carry no id
* `客户端断开连接` marks teardown; `连接资源已释放` closes the session
* a new handshake (`conn - Headers:`, `收到hello消息`), a new session id, or a
  server start (`启动全局GC管理器`) also closes the previous session
* lines without a timestamp belong to the preceding record
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LOG = REPO_ROOT / "my_explorations/server/deploy/logs/server.log"
GENERATOR_VERSION = 1

RECORD_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - (.*)$")
SESSION_RE = re.compile(
    r'"session_id"\s*:\s*"'
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
    r'"'
)
DEVICE_RE = re.compile(r"'device-id'\s*:\s*'([^']+)'")
HELLO_DEVICE_RE = re.compile(r'"device_(?:id|mac)"\s*:\s*"([^"]+)"')
PHOTO_RE = re.compile(r"PHOTO\s+(/photos/[^\s]+)")
TURN_RE = re.compile(r'收到listen消息.*"state"\s*:\s*"start"')
ASR_TEXT_RE = re.compile(r"识别文本[:：]\s*(.+)$")
ARTIFACT_NAME_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})-[^.]+\.(?:jpe?g|png)$", re.I)

END_LABELS = {
    "release": "连接释放",
    "disconnect": "客户端断开",
    "new_session": "新会话",
    "new_connection": "新连接",
    "server_restart": "服务重启",
    "eof": "日志结束",
}


@dataclass(eq=False)
class Session:
    id: str
    start: datetime
    line_start: int
    device: str | None = None
    lines: list[str] = field(default_factory=list)
    line_end: int = 0
    last_ts: datetime | None = None
    end: datetime | None = None
    end_reason: str = "eof"
    turns: int = 0
    first_text: str | None = None
    closing: bool = False
    artifacts: list[str] = field(default_factory=list)
    segments: list[dict] = field(default_factory=list)
    markers: list[tuple[int, datetime]] = field(default_factory=list)
    segment_start: datetime | None = None
    segment_line_start: int = 0

    @property
    def short(self) -> str:
        return self.id.replace("-", "")[:8]

    @property
    def duration_s(self) -> int:
        if self.end is None:
            return 0
        return max(0, int((self.end - self.start).total_seconds()))

    def add(self, raw: str, lineno: int, ts: datetime | None) -> None:
        self.lines.append(raw)
        self.line_end = lineno
        if ts is not None:
            self.last_ts = ts
        self.note(raw)

    def note(self, raw: str) -> None:
        if TURN_RE.search(raw):
            self.turns += 1
        if self.first_text is None:
            m = ASR_TEXT_RE.search(raw)
            if m:
                self.first_text = m.group(1).strip()[:200]

    @property
    def bytes(self) -> int:
        return sum(len(line.encode("utf-8", "replace")) for line in self.lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Split xiaozhi-server's server.log into per-session folders."
    )
    p.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help="raw server.log (default: deploy/logs/server.log)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default: <log directory>/sessions)",
    )
    p.add_argument(
        "--photos",
        type=Path,
        default=None,
        help="photos directory (default: <log directory>/photos)",
    )
    p.add_argument(
        "--artifact-root",
        action="append",
        type=Path,
        default=[],
        help="extra artifact directory to group by session (repeatable)",
    )
    p.add_argument(
        "--copy-artifacts",
        action="store_true",
        help="copy artifacts instead of hardlinking them",
    )
    p.add_argument("--no-artifacts", action="store_true", help="skip artifact grouping")
    p.add_argument(
        "--force",
        action="store_true",
        help="replace a non-empty --out directory even without .generated.json",
    )
    p.add_argument("--quiet", action="store_true", help="only print the result path")
    return p.parse_args(argv)


def fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def iso(ts: datetime | None) -> str | None:
    return ts.strftime("%Y-%m-%dT%H:%M:%S") if ts else None


def md_cell(value: str | None, limit: int = 48) -> str:
    text = " ".join((value or "").split()).replace("|", r"\|")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text or "—"


def artifact_time(rel: Path) -> datetime | None:
    """Infer `YYYY-MM-DD/HH-MM-SS-*.jpg` style timestamps."""
    if len(rel.parts) < 2:
        return None
    try:
        day = datetime.strptime(rel.parts[-2], "%Y-%m-%d")
    except ValueError:
        return None
    m = ARTIFACT_NAME_RE.match(rel.name)
    if not m:
        return None
    hour, minute, second = (int(part) for part in m.groups())
    try:
        return day.replace(hour=hour, minute=minute, second=second)
    except ValueError:
        return None


class Splitter:
    def __init__(self):
        self.sessions: list[Session] = []
        self.global_lines: dict[str, list[str]] = {}
        self.photo_refs: dict[str, Session] = {}
        self.total_lines = 0
        self.pending_device: str | None = None
        self.current: Session | None = None
        self.by_id: dict[str, Session] = {}
        self.tail_session: Session | None = None
        self.last_target: tuple[str, Session | str] | None = None

    # ---- line accounting ----
    def _add_global(self, raw: str, day: str) -> None:
        self.global_lines.setdefault(day, []).append(raw)
        self.last_target = ("global", day)

    def _add_session(
        self,
        session: Session,
        raw: str,
        lineno: int,
        ts: datetime | None,
        body: str,
    ) -> None:
        session.add(raw, lineno, ts)
        self.last_target = ("session", session)
        photo = PHOTO_RE.search(body)
        if photo:
            key = photo.group(1).lstrip("/")
            self.photo_refs.setdefault(key, session)

    def _close(self, reason: str, end: datetime | None = None) -> None:
        session = self.current
        if session is None:
            return
        session.end_reason = reason
        session.end = end or session.last_ts or session.segment_start or session.start
        session.segments.append(
            {
                "start": session.segment_start or session.start,
                "end": session.end,
                "reason": reason,
                "line_start": session.segment_line_start,
                "line_end": session.line_end,
            }
        )
        session.segment_start = None
        session.closing = False
        self.current = None

    def _start(self, sid: str, ts: datetime, lineno: int) -> None:
        session = self.by_id.get(sid)
        if session is None:
            session = Session(
                id=sid, start=ts, line_start=lineno, device=self.pending_device
            )
            self.sessions.append(session)
            self.by_id[sid] = session
        else:
            # A client may reconnect with the same session_id. Keep one logical
            # session (matching the log-viewer) and mark the join point inline.
            session.markers.append((len(session.lines), ts))
            if not session.device:
                session.device = self.pending_device
        session.segment_start = ts
        session.segment_line_start = lineno
        self.current = session

    # ---- main parse ----
    def parse(self, log_path: Path) -> None:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for lineno, raw in enumerate(handle, 1):
                self.total_lines += 1
                raw_text = raw.rstrip("\n")
                m = RECORD_RE.match(raw_text)

                if not m:
                    # Timestamp-less continuation line: keep it with its record.
                    target = self.last_target
                    if target is None:
                        self._add_global(raw, "unknown")
                    elif target[0] == "session":
                        session = target[1]
                        assert isinstance(session, Session)
                        session.add(raw, lineno, None)
                    else:
                        self._add_global(raw, str(target[1]))
                    continue

                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                body = m.group(2)
                day = ts.strftime("%Y-%m-%d")

                # Duplicate `连接资源已释放` lines belong to the session that
                # just closed, not to the global bucket.
                if self.tail_session is not None:
                    if "连接资源已释放" in body:
                        session = self.tail_session
                        self._add_session(session, raw, lineno, ts, body)
                        session.end = ts
                        session.segments[-1]["end"] = ts
                        session.segments[-1]["line_end"] = lineno
                        self.last_target = ("session", session)
                        continue
                    self.tail_session = None

                # Handshake = new connection: close the old session and keep
                # the handshake itself in the global bucket.
                if "conn - Headers:" in body or "收到hello消息" in body:
                    if self.current is not None:
                        self._close("new_connection")
                    dev = DEVICE_RE.search(body) or HELLO_DEVICE_RE.search(body)
                    if dev:
                        self.pending_device = dev.group(1).strip()
                    self._add_global(raw, day)
                    continue

                # Server start: anything still open ended when the process went away.
                if "启动全局GC管理器" in body:
                    if self.current is not None:
                        self._close("server_restart")
                    self.pending_device = None
                    self._add_global(raw, day)
                    continue

                sid_match = SESSION_RE.search(body)
                if sid_match:
                    sid = sid_match.group(1).lower()
                    if self.current is not None and self.current.id != sid:
                        self._close("new_session")
                    if self.current is None:
                        self._start(sid, ts, lineno)
                    assert self.current is not None
                    self._add_session(self.current, raw, lineno, ts, body)
                    continue

                # Teardown. Keep the closing lines in the session; `连接资源已释放`
                # is the actual end marker, `客户端断开连接` only starts teardown.
                if "客户端断开连接" in body:
                    if self.current is not None:
                        self.current.closing = True
                        self._add_session(self.current, raw, lineno, ts, body)
                    else:
                        self._add_global(raw, day)
                    continue

                if "连接资源已释放" in body:
                    if self.current is not None:
                        session = self.current
                        self._add_session(session, raw, lineno, ts, body)
                        session.end_reason = "release"
                        self._close("release", ts)
                        self.tail_session = session
                    else:
                        self._add_global(raw, day)
                    continue

                if self.current is not None:
                    self._add_session(self.current, raw, lineno, ts, body)
                else:
                    self._add_global(raw, day)

        if self.current is not None:
            self._close("disconnect" if self.current.closing else "eof")

        written = sum(len(s.lines) for s in self.sessions) + sum(
            len(lines) for lines in self.global_lines.values()
        )
        if self.total_lines != written:
            raise RuntimeError(
                f"line accounting mismatch: source {self.total_lines}, written {written}"
            )

        self.sessions.sort(key=lambda s: (s.start, s.id))


def collect_artifacts(
    roots: list[tuple[str, Path]],
) -> dict[str, Path]:
    """Map `photos/2026-11-14/xxx.jpg` -> real path."""
    found: dict[str, Path] = {}
    for name, root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                key = f"{name}/{path.relative_to(root).as_posix()}"
                found[key] = path
    return found


def assign_artifacts(
    splitter: Splitter,
    artifacts: dict[str, Path],
) -> tuple[dict[Session, list[str]], list[str]]:
    assigned: dict[Session, list[str]] = {s: [] for s in splitter.sessions}
    unassigned: list[str] = []

    # Match artifacts against each connection segment, not the whole (possibly
    # reconnected) session: a photo taken while the client was away must not be
    # credited to the previous segment.
    windows: list[tuple[datetime, datetime, Session]] = []
    for session in splitter.sessions:
        for segment in session.segments:
            windows.append((segment["start"], segment["end"], session))
    windows.sort(key=lambda item: item[0])

    for key in artifacts:
        session = splitter.photo_refs.get(key)
        if session is None:
            stamp = artifact_time(Path(key.split("/", 1)[1]))
            if stamp is not None:
                matches = [
                    item for item in windows if item[0] <= stamp <= item[1]
                ]
                if matches:
                    session = max(matches, key=lambda item: item[0])[2]
        if session is None:
            unassigned.append(key)
        else:
            assigned[session].append(key)

    for items in assigned.values():
        items.sort()
    unassigned.sort()
    return assigned, unassigned


def materialize(src: Path, dest: Path, copy: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    if copy:
        shutil.copy2(src, dest)
        return
    try:
        os.link(src, dest)
    except OSError:
        # Cross-device, permissions, etc.: fall back to a real copy.
        shutil.copy2(src, dest)


def session_dirname(session: Session, used: set[str]) -> str:
    for attempt in range(1, 100):
        suffix = "" if attempt == 1 else f"-{attempt}"
        name = f"{session.start:%H-%M-%S}_{session.short}{suffix}"
        if name not in used:
            used.add(name)
            return name
    raise RuntimeError(f"cannot allocate a directory name for {session.id}")


def write_session(
    root: Path,
    rel_dir: str,
    session: Session,
    artifacts: list[str],
    artifact_paths: dict[str, Path],
    copy_artifacts: bool,
    source_name: str,
) -> dict:
    target = root / rel_dir
    target.mkdir(parents=True, exist_ok=True)

    header = [
        f"# session {session.id}\n",
        f"# device {session.device or '-'}\n",
        f"# start {session.start:%Y-%m-%d %H:%M:%S}  "
        f"end {session.end:%Y-%m-%d %H:%M:%S}\n",
        f"# turns {session.turns}  lines {len(session.lines)}  "
        f"end_reason {session.end_reason}\n",
        f"# source {source_name} lines {session.line_start}-{session.line_end}\n",
    ]
    if len(session.segments) > 1:
        header.append(
            f"# segments {len(session.segments)} "
            "(reconnect markers are shown in the body)\n"
        )
    if artifacts:
        header.append("# artifacts\n")
        header.extend(f"#   {key}\n" for key in artifacts)
    header.append("#\n")

    markers: dict[int, list[datetime]] = {}
    for index, stamp in session.markers:
        markers.setdefault(index, []).append(stamp)
    body: list[str] = []
    for index, line in enumerate(session.lines):
        for stamp in markers.get(index, ()):
            body.append(f"# --- reconnect {stamp:%Y-%m-%d %H:%M:%S} ---\n")
        body.append(line)
    for stamp in markers.get(len(session.lines), ()):
        body.append(f"# --- reconnect {stamp:%Y-%m-%d %H:%M:%S} ---\n")

    (target / "session.log").write_text(
        "".join(header) + "".join(body), encoding="utf-8"
    )

    for key in artifacts:
        materialize(artifact_paths[key], target / key, copy_artifacts)
    session.artifacts = artifacts

    segments = [
        {
            "start": iso(segment["start"]),
            "end": iso(segment["end"]),
            "reason": segment["reason"],
            "line_start": segment["line_start"],
            "line_end": segment["line_end"],
        }
        for segment in session.segments
    ]
    meta = {
        "id": session.id,
        "short": session.short,
        "device": session.device,
        "start": iso(session.start),
        "end": iso(session.end),
        "duration_s": session.duration_s,
        "turns": session.turns,
        "lines": len(session.lines),
        "bytes": session.bytes,
        "end_reason": session.end_reason,
        "first_text": session.first_text,
        "segments": segments,
        "source": {
            "file": source_name,
            "line_start": session.line_start,
            "line_end": session.line_end,
        },
        "log": "session.log",
        "artifacts": artifacts,
    }
    (target / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return meta


def write_global(root: Path, global_lines: dict[str, list[str]]) -> int:
    target = root / "_global"
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    for day in sorted(global_lines):
        lines = global_lines[day]
        total += len(lines)
        header = (
            f"# global log lines (no active session) - {day}\n"
            f"# lines {len(lines)}\n"
            "# these are startup/shutdown/handshake lines, not part of a session\n"
            "#\n"
        )
        (target / f"{day}.log").write_text(
            header + "".join(lines), encoding="utf-8"
        )
    return total


def write_unassigned(root: Path, keys: list[str], paths: dict[str, Path], copy: bool) -> None:
    if not keys:
        return
    for key in keys:
        materialize(paths[key], root / "_unassigned" / key, copy)


def write_index(
    root: Path,
    metas: list[dict],
    source: Path,
    total_lines: int,
    global_count: int,
    assigned_artifacts: int,
    unassigned_artifacts: int,
) -> None:
    with (root / "index.jsonl").open("w", encoding="utf-8") as handle:
        for meta in metas:
            handle.write(json.dumps(meta, ensure_ascii=False) + "\n")

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Server sessions\n",
        "\n",
        f"Source: `{source.name}` · {total_lines:,} lines · "
        f"{source.stat().st_size / (1024 * 1024):.1f} MB  \n",
        f"Generated: {generated}  \n",
        f"Sessions: **{len(metas)}** · global lines: {global_count:,} · "
        f"artifacts: {assigned_artifacts} grouped, {unassigned_artifacts} unassigned\n",
        "\n",
        "Each session lives in its own folder next to this file: "
        "`session.log`, `meta.json`, and grouped artifacts (hardlinks to the "
        "originals). `index.jsonl` is the machine-readable version.\n",
        "\n",
        "- Non-session lines (startup, shutdown, handshake): `_global/<date>.log`\n",
        "- Artifacts outside every session window: `_unassigned/`\n",
        "\n",
        "| Start | Duration | Device | Session | Seg | Turns | Lines | Artifacts | End | First utterance |\n",
        "|---|---|---|---|---:|---:|---:|---:|---|---|\n",
    ]
    for meta in sorted(metas, key=lambda m: m["start"] or "", reverse=True):
        day, clock = (meta["start"] or "").split("T")
        link = f"[{day} {clock}]({meta['dir']}/session.log)"
        device = f"`{meta['device']}`" if meta.get("device") else "—"
        artifacts = f"{len(meta['artifacts'])}" if meta["artifacts"] else "—"
        segments = len(meta.get("segments") or [])
        seg = str(segments) if segments > 1 else "—"
        end = END_LABELS.get(meta["end_reason"], meta["end_reason"])
        lines.append(
            f"| {link} | {fmt_duration(meta['duration_s'])} | {device} | "
            f"[`{meta['short']}`]({meta['dir']}/session.log) | {seg} | "
            f"{meta['turns']} | {meta['lines']} | {artifacts} | {end} | "
            f"{md_cell(meta.get('first_text'))} |\n"
        )
    if not metas:
        lines.append("| — | — | — | — | — | — | — | — | — | — |\n")

    if unassigned_artifacts:
        lines.extend(
            [
                "\n",
                f"Unassigned artifacts ({unassigned_artifacts}) are in "
                f"`_unassigned/` (taken outside any known session window).\n",
            ]
        )
    (root / "index.md").write_text("".join(lines), encoding="utf-8")

    write_html_index(
        root,
        metas,
        source,
        total_lines,
        global_count,
        assigned_artifacts,
        unassigned_artifacts,
    )


def _photo_cell(meta: dict) -> str:
    images = [
        item
        for item in meta["artifacts"]
        if item.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    others = [item for item in meta["artifacts"] if item not in images]
    if not images and not others:
        return "—"
    parts = []
    for item in images[:4]:
        href = f"{meta['dir']}/{item}"
        parts.append(
            f'<a href="{escape(href)}" title="{escape(item)}">'
            f'<img class="thumb" src="{escape(href)}" loading="lazy" alt=""></a>'
        )
    if len(images) > 4:
        parts.append(f'<span class="more">+{len(images) - 4}</span>')
    for item in others[:2]:
        href = f"{meta['dir']}/{item}"
        parts.append(
            f'<a class="file" href="{escape(href)}" title="{escape(item)}">'
            f"{escape(Path(item).name)}</a>"
        )
    if len(others) > 2:
        parts.append(f'<span class="more">+{len(others) - 2}</span>')
    return "".join(parts)


def write_html_index(
    root: Path,
    metas: list[dict],
    source: Path,
    total_lines: int,
    global_count: int,
    assigned_artifacts: int,
    unassigned_artifacts: int,
) -> None:
    global_files = sorted((root / "_global").glob("*.log"))
    unassigned_files = sorted((root / "_unassigned").rglob("*"))
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[str] = []
    for meta in sorted(metas, key=lambda m: m["start"] or "", reverse=True):
        start = (meta["start"] or "").replace("T", " ")
        log_href = f"{meta['dir']}/session.log"
        meta_href = f"{meta['dir']}/meta.json"
        device = escape(meta["device"]) if meta.get("device") else "—"
        segments = len(meta.get("segments") or [])
        seg = str(segments) if segments > 1 else "—"
        end = escape(END_LABELS.get(meta["end_reason"], meta["end_reason"]))
        first = meta.get("first_text") or "—"
        if len(first) > 160:
            first = first[:159] + "…"
        rows.append(
            "<tr>"
            f'<td class="nowrap"><a href="{escape(log_href)}">{escape(start)}</a></td>'
            f'<td class="nowrap">{fmt_duration(meta["duration_s"])}</td>'
            f'<td class="nowrap"><code>{device}</code></td>'
            f'<td class="nowrap"><a class="sess" href="{escape(log_href)}">'
            f'{escape(meta["short"])}</a> '
            f'<a class="meta" href="{escape(meta_href)}">meta</a></td>'
            f"<td>{seg}</td><td>{meta['turns']}</td><td>{meta['lines']}</td>"
            f"<td class=\"photos\">{_photo_cell(meta)}</td>"
            f"<td class=\"nowrap\">{end}</td>"
            f'<td class="first">{escape(first)}</td>'
            "</tr>\n"
        )

    globals_html = (
        " · ".join(
            f'<a href="_global/{escape(path.name)}">{escape(path.name)}</a>'
            for path in global_files
        )
        or "—"
    )
    unassigned_html = "".join(
        f'<li><a href="_unassigned/{escape(path.relative_to(root / "_unassigned").as_posix())}">'
        f"{escape(path.relative_to(root / '_unassigned').as_posix())}</a></li>"
        for path in unassigned_files
        if path.is_file()
    ) or "<li>—</li>"

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Server sessions</title>
<style>
  :root {{ --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#c9d1d9;
          --muted:#8b949e; --link:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:18px 22px; background:var(--bg); color:var(--text);
         font:13px/1.5 -apple-system,"SF Mono",Menlo,Consolas,monospace; }}
  h1 {{ font-size:18px; margin:0 0 8px; }}
  h2 {{ font-size:14px; margin:26px 0 8px; }}
  a {{ color:var(--link); text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .stats {{ color:var(--muted); }}
  .links {{ color:var(--muted); margin:6px 0 16px; }}
  table {{ border-collapse:collapse; width:100%; background:var(--panel); }}
  th, td {{ border-bottom:1px solid var(--border); padding:6px 8px; text-align:left;
            vertical-align:middle; }}
  th {{ position:sticky; top:0; background:#1b222b; font-size:11px;
        text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
  tr:hover td {{ background:rgba(255,255,255,.03); }}
  .nowrap {{ white-space:nowrap; }}
  code {{ color:#79c0ff; }}
  .sess {{ font-weight:600; }}
  .meta {{ color:var(--muted); font-size:11px; }}
  .first {{ color:var(--muted); max-width:420px; overflow-wrap:anywhere; }}
  .photos {{ white-space:nowrap; }}
  .thumb {{ width:80px; height:45px; object-fit:cover; border:1px solid var(--border);
            border-radius:3px; vertical-align:middle; margin-right:3px; }}
  .more {{ color:var(--muted); font-size:11px; }}
  .file {{ display:inline-block; font-size:11px; margin-right:4px; }}
  ul {{ margin:6px 0 0 18px; padding:0; }}
</style>
</head>
<body>
<h1>Server sessions</h1>
<div class="stats">Source <code>{escape(source.name)}</code> · {total_lines:,} lines ·
{source.stat().st_size / (1024 * 1024):.1f} MB · generated {generated}</div>
<div class="stats"><b>{len(metas)}</b> sessions · {global_count:,} global lines ·
{assigned_artifacts} artifacts grouped · {unassigned_artifacts} unassigned</div>
<div class="links">Non-session lines: {globals_html}</div>
<table>
<thead><tr><th>Start</th><th>Duration</th><th>Device</th><th>Session</th>
<th>Seg</th><th>Turns</th><th>Lines</th><th>Artifacts</th><th>End</th>
<th>First utterance</th></tr></thead>
<tbody>
{''.join(rows)}</tbody>
</table>
<h2>Unassigned artifacts</h2>
<ul>{unassigned_html}</ul>
</body>
</html>
"""
    (root / "index.html").write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    log = args.log.expanduser().resolve()
    out = (args.out or (log.parent / "sessions")).expanduser().resolve()

    if not log.is_file():
        raise SystemExit(f"log not found: {log}")
    if out == log or out == log.parent:
        raise SystemExit("--out must not be the log file or its directory")

    if out.exists() and any(out.iterdir()):
        if not (out / ".generated.json").is_file() and not args.force:
            raise SystemExit(
                f"{out} is not empty and has no .generated.json; "
                "use --force only if you are sure it is disposable"
            )

    roots: list[tuple[str, Path]] = []
    if not args.no_artifacts:
        photos = (args.photos or (log.parent / "photos")).expanduser().resolve()
        roots.append(("photos", photos))
        for extra in args.artifact_root:
            extra = extra.expanduser().resolve()
            roots.append((extra.name, extra))
    seen: set[str] = set()
    for name, _ in roots:
        if name in seen:
            raise SystemExit(f"duplicate artifact root name: {name}")
        seen.add(name)

    if not args.quiet:
        print(f"reading {log} ({log.stat().st_size / (1024 * 1024):.1f} MB)")

    splitter = Splitter()
    splitter.parse(log)

    artifact_paths = collect_artifacts(roots)
    assigned, unassigned = assign_artifacts(splitter, artifact_paths)

    tmp = out.parent / f".{out.name}.tmp-{os.getpid()}"
    old = out.parent / f".{out.name}.old-{os.getpid()}"
    for stale in (tmp, old):
        if stale.exists():
            shutil.rmtree(stale)
    tmp.mkdir(parents=True)

    try:
        used: set[str] = set()
        used_days: dict[str, set[str]] = {}
        metas: list[dict] = []
        for session in splitter.sessions:
            day = session.start.strftime("%Y-%m-%d")
            used_days.setdefault(day, set())
            name = session_dirname(session, used_days[day])
            rel_dir = f"{day}/{name}"
            meta = write_session(
                tmp,
                rel_dir,
                session,
                assigned.get(session, []),
                artifact_paths,
                args.copy_artifacts,
                log.name,
            )
            meta["dir"] = rel_dir
            metas.append(meta)

        global_count = write_global(tmp, splitter.global_lines)
        write_unassigned(tmp, unassigned, artifact_paths, args.copy_artifacts)
        write_index(
            tmp,
            metas,
            log,
            splitter.total_lines,
            global_count,
            sum(len(items) for items in assigned.values()),
            len(unassigned),
        )

        manifest = {
            "generator": "split-sessions.py",
            "version": GENERATOR_VERSION,
            "source": str(log),
            "source_lines": splitter.total_lines,
            "source_bytes": log.stat().st_size,
            "source_mtime": int(log.stat().st_mtime),
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "sessions": len(metas),
            "global_lines": global_count,
            "artifacts": {
                "grouped": sum(len(items) for items in assigned.values()),
                "unassigned": len(unassigned),
            },
            "copy_artifacts": args.copy_artifacts,
        }
        (tmp / ".generated.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if out.exists():
            out.rename(old)
        tmp.rename(out)
        if old.exists():
            shutil.rmtree(old)
    except BaseException:
        if tmp.exists():
            shutil.rmtree(tmp)
        raise

    if args.quiet:
        print(out)
    else:
        print(
            f"wrote {len(metas)} sessions, {global_count} global lines, "
            f"{manifest['artifacts']['grouped']} artifacts "
            f"({manifest['artifacts']['unassigned']} unassigned)"
        )
        print(f"index: {out / 'index.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
