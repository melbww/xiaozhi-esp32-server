"""多源实时日志流。

聚合多个日志源并把每行广播给订阅者(WebSocket 客户端):

- ``server``  : ``docker logs -f xiaozhi-esp32-server`` —— xiaozhi-server 的全部输出
               (loguru 行 + httpx HTTP Request + FunASR tqdm 进度), 最全的一份。
- ``runtime`` : 本运行时自己的日志文件(唤醒词/音频事件)。

每个订阅者持有一个队列, 由各自线程消费。广播带一个 ring buffer 供新客户端拿历史。
"""
import json
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path

DEFAULT_CONTAINER = "xiaozhi-esp32-server"


class LogStreamer:
    def __init__(
        self,
        container_name: str = DEFAULT_CONTAINER,
        runtime_log: Path | None = None,
        history: int = 50,
    ) -> None:
        self.container_name = container_name
        self.runtime_log = runtime_log
        self.history = max(history, 10)
        self._subscribers: list[queue.Queue[str]] = []
        self._lock = threading.Lock()
        self._running = False
        self._started = False
        self._recent: list[dict] = []

    # ---------------- 生命周期 ----------------
    def _ensure_started(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        self._running = True
        if shutil.which("docker"):
            threading.Thread(
                target=self._run_docker_source,
                daemon=True,
                name="logstream-docker",
            ).start()
        else:
            self._broadcast(self._frame("server", "error", "docker 未找到, 无法流式获取 xiaozhi-server 日志"))
        if self.runtime_log is not None:
            threading.Thread(
                target=self._run_file_source,
                daemon=True,
                name="logstream-file",
            ).start()

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self._running = False

    # ---------------- 订阅 ----------------
    def subscribe(self) -> queue.Queue[str]:
        self._ensure_started()
        client_queue: queue.Queue[str] = queue.Queue(maxsize=2000)
        with self._lock:
            self._subscribers.append(client_queue)
        return client_queue

    def unsubscribe(self, client_queue: queue.Queue[str]) -> None:
        with self._lock:
            if client_queue in self._subscribers:
                self._subscribers.remove(client_queue)

    def recent(self, limit: int | None = None) -> list[dict]:
        limit = limit or self.history
        with self._lock:
            return list(self._recent[-limit:])

    # ---------------- 广播 ----------------
    @staticmethod
    def _frame(source: str, level: str, line: str) -> dict:
        return {"source": source, "level": level, "ts": time.time(), "line": line}

    def _broadcast(self, frame: dict) -> None:
        text = json.dumps(frame, ensure_ascii=False)
        with self._lock:
            self._recent.append(frame)
            if len(self._recent) > 1000:
                self._recent = self._recent[-1000:]
            subscribers = list(self._subscribers)
        for client_queue in subscribers:
            try:
                client_queue.put_nowait(text)
            except queue.Full:
                pass

    # ---------------- 日志级别(尽力而为) ----------------
    @staticmethod
    def _detect_level(line: str) -> str:
        upper = line.upper()
        for token in ("-ERROR-", " - ERROR - ", "[ERROR]"):
            if token in upper:
                return "error"
        for token in ("-WARNING-", "-WARN-", " - WARNING - ", "[WARNING]"):
            if token in upper:
                return "warn"
        for token in ("-DEBUG-", " - DEBUG - ", "[DEBUG]"):
            if token in upper:
                return "debug"
        return "info"

    # ---------------- docker 源 ----------------
    def _run_docker_source(self) -> None:
        # 只带少量最近行作为上下文, 避免重放大量旧日志导致打开慢
        tail = min(self.history, 20)
        cmd = ["docker", "logs", "-f", "--tail", str(tail), self.container_name]
        while self._running:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                self._broadcast(self._frame("server", "info", f"[logs] 已连接 docker logs {self.container_name}"))
                for raw_line in proc.stdout:
                    if not self._running:
                        proc.terminate()
                        break
                    line = raw_line.rstrip("\r\n")
                    if line:
                        self._broadcast(self._frame("server", self._detect_level(line), line))
                proc.wait()
                if self._running:
                    self._broadcast(self._frame("server", "warn", "[logs] docker logs 断开, 3s 后重连..."))
                    time.sleep(3)
            except FileNotFoundError:
                self._broadcast(self._frame("server", "error", "docker 命令不可用"))
                return
            except Exception as exc:
                self._broadcast(self._frame("server", "error", f"docker logs 异常: {exc}"))
                if self._running:
                    time.sleep(3)

    # ---------------- 文件源(运行时自身日志) ----------------
    def _run_file_source(self) -> None:
        path: Path = self.runtime_log
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                # 从文件末尾开始, 只推实时新行, 不重放历史(避免翻出很久以前的会话)
                handle.seek(0, 2)
                self._broadcast(self._frame("runtime", "info", f"[logs] 已连接 runtime 日志 {path}"))
                while self._running:
                    line = handle.readline()
                    if line:
                        self._broadcast(self._frame("runtime", self._detect_level(line), line.rstrip("\r\n")))
                    else:
                        time.sleep(0.2)
        except FileNotFoundError:
            self._broadcast(self._frame("runtime", "warn", f"[logs] 日志文件不存在: {path}"))
        except Exception as exc:
            self._broadcast(self._frame("runtime", "error", f"runtime 日志 tail 异常: {exc}"))
