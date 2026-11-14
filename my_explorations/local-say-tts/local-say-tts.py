#!/usr/bin/env python3
"""Local macOS `say` TTS HTTP service for xiaozhi-esp32-server CustomTTS.

This is a free, offline, low-latency fallback for Edge TTS. It accepts the
same POST shape as the CustomTTS provider and returns a 22.05 kHz mono WAV.

Usage:
    python3 local-say-tts.py                 # foreground, port 8880
    SAY_TTS_VOICE_ZH='Yue (Premium)' SAY_TTS_VOICE_EN='Zoe (Premium)' \
        python3 local-say-tts.py

CustomTTS config in the 智控台:
    url:    http://host.docker.internal:8880/tts
    method: POST
    params: {"input": "{prompt_text}"}
    format: wav

Voice routing: text containing CJK characters uses SAY_TTS_VOICE_ZH
(default `Yue (Premium)`), everything else uses SAY_TTS_VOICE_EN
(default `Zoe (Premium)`). An explicit request `voice` field always wins;
setting SAY_TTS_VOICE forces one voice for all text.

Voices: `say -v '?' | grep -E 'zh|en_US'` (Meijia is Taiwanese, Tingting is
mainland, Sinji is Cantonese). The service is intentionally LAN-only; do not
expose it to the public internet.
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("SAY_TTS_HOST", "0.0.0.0")
PORT = int(os.environ.get("SAY_TTS_PORT", "8880"))
VOICE_ZH = os.environ.get("SAY_TTS_VOICE_ZH", "Yue (Premium)")
VOICE_EN = os.environ.get("SAY_TTS_VOICE_EN", "Zoe (Premium)")
FORCED_VOICE = os.environ.get("SAY_TTS_VOICE", "").strip()
DEFAULT_RATE = int(os.environ.get("SAY_TTS_RATE", "180"))
MAX_CONCURRENT = int(os.environ.get("SAY_TTS_MAX_CONCURRENT", "4"))
SAY = "/usr/bin/say"
AFCONVERT = "/usr/bin/afconvert"
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def pick_voice(text: str, requested: str = "") -> str:
    """Choose a voice: explicit request > forced env > CJK/English routing."""
    requested = (requested or "").strip()
    if requested and requested.lower() != "auto":
        return requested
    if FORCED_VOICE:
        return FORCED_VOICE
    return VOICE_ZH if CJK_RE.search(text) else VOICE_EN


_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT)


def synthesize(text: str, voice: str, rate: int) -> bytes:
    with _semaphore, tempfile.TemporaryDirectory(prefix="say-tts-") as tmp:
        aiff = os.path.join(tmp, "out.aiff")
        wav = os.path.join(tmp, "out.wav")
        subprocess.run(
            [SAY, "-v", voice, "-r", str(rate), "-o", aiff, text],
            check=True,
            timeout=30,
        )
        subprocess.run(
            [AFCONVERT, "-f", "WAVE", "-d", "LEI16@22050", aiff, wav],
            check=True,
            timeout=30,
        )
        with open(wav, "rb") as f:
            return f.read()


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalSayTTS/1.0"

    def log_message(self, fmt, *args):
        print(f"{time.strftime('%H:%M:%S')} {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self):
        if self.path in ("/health", "/"):
            body = json.dumps(
                {
                    "status": "ok",
                    "voice_zh": VOICE_ZH,
                    "voice_en": VOICE_EN,
                    "forced_voice": FORCED_VOICE or None,
                    "rate": DEFAULT_RATE,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            text = payload.get("input") or payload.get("text") or ""
            rate = int(payload.get("rate") or DEFAULT_RATE)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty input")
            text = text.strip()
            voice = pick_voice(text, payload.get("voice"))
            started = time.time()
            audio = synthesize(text, voice, rate)
            print(
                f"{time.strftime('%H:%M:%S')} tts {len(audio)} bytes "
                f"in {time.time() - started:.2f}s voice={voice} text={text[:40]!r}",
                flush=True,
            )
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"Local say TTS listening on http://{HOST}:{PORT}/tts "
        f"(zh={VOICE_ZH}, en={VOICE_EN}, "
        f"forced={FORCED_VOICE or 'auto'}, rate={DEFAULT_RATE})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
