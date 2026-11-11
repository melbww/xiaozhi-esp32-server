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
from urllib.parse import urlparse

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parents[1]
DEFAULT_CONFIG = APP_DIR / "sources.json"
DEFAULT_HISTORY = 200
DEFAULT_PORT = 8007

LEVEL_TOKENS = (
    ("error", ("-ERROR-", " - ERROR - ", "[ERROR]", "ERROR:")),
    ("warn", ("-WARNING-", "-WARN-", " - WARNING - ", "[WARNING]", "WARN:")),
    ("debug", ("-DEBUG-", " - DEBUG - ", "[DEBUG]")),
)


@dataclass(frozen=True)
class SourceSpec:
    """One log source: a docker container or a file on the host."""

    name: str
    kind: str  # "docker" | "file"
    target: str
    label: str = ""
    tail: int = 20

    @property
    def display(self) -> str:
        return self.label or self.name


# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
def load_sources(config_path: Path, history_override: int | None = None) -> tuple[list[SourceSpec], int]:
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"config not found: {config_path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON in {config_path}: {exc}")

    if isinstance(raw, list):
        entries = raw
        history = DEFAULT_HISTORY
    else:
        entries = raw.get("sources") or []
        history = int(raw.get("history", DEFAULT_HISTORY))

    if history_override is not None:
        history = history_override

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
            )
        )

    if not sources:
        raise SystemExit(f"no enabled sources in {config_path}")
    return sources, max(int(history), 10)


def _resolve_path(target: str) -> str:
    """Resolve a file target: absolute, ~, or relative to the repo root."""
    path = Path(target).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path.resolve())


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #
class LogStreamer:
    """Tails every source and fans frames out to websocket subscribers."""

    def __init__(self, sources: list[SourceSpec], history: int = DEFAULT_HISTORY) -> None:
        self.sources = list(sources)
        self.history = history
        self._subscribers: list[queue.Queue[str]] = []
        self._recent: list[str] = []
        self._lock = threading.Lock()
        self._running = False
        self._started = False
        self._status: dict[str, dict] = {
            src.name: {"connected": False, "lines": 0, "lastLineAt": None, "note": ""}
            for src in self.sources
        }

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
                    **self._status[src.name],
                }
                for src in self.sources
            ]

    # ---- publish ----
    def _publish(self, name: str, level: str, line: str) -> None:
        if not line:
            return
        frame = {"source": name, "level": level, "line": line, "ts": round(time.time(), 3)}
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
                    line = raw_line.rstrip("\r\n")
                    if line:
                        since = time.time()
                        self._publish(src.name, self._detect_level(line), line)
                proc.wait()
            finally:
                if proc.poll() is None:
                    proc.terminate()

            if not self._running:
                break

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
                        self._publish(src.name, self._detect_level(line), line.rstrip("\r\n"))
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
                }
            )
            return

        if path == "/api/sources":
            self._send_json({"sources": self.streamer.snapshot()})
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

            recent_frames = self.streamer.recent(50)
            hello = json.dumps(
                {
                    "type": "logs_hello",
                    "payload": {
                        "sources": self.streamer.snapshot(),
                        "history": len(recent_frames),
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

    sources, history = load_sources(config_path, args.history)

    if args.list_sources:
        print(f"config: {config_path}  (history={history})")
        for src in sources:
            print(f"  {src.name:10s} {src.kind:7s} {src.target}  [{src.display}]")
        return 0

    streamer = LogStreamer(sources, history=history)
    handler = partial(LogViewerHandler, streamer=streamer)

    try:
        server = ThreadingHTTPServer((args.host, args.port), handler)
    except OSError as exc:
        print(f"cannot listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    server.daemon_threads = True

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"log viewer : http://{shown_host}:{args.port}/logs.html")
    print(f"log stream : ws://{shown_host}:{args.port}/logs-ws")
    print(f"sources    : {', '.join(f'{s.name}({s.kind})' for s in sources)}")
    print("press Ctrl+C to stop")

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
