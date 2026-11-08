# Local macOS `say` TTS for the robot

Free, offline, low-latency TTS fallback for `xiaozhi-esp32-server` `CustomTTS`.
This is part of the **robot voice stack**; it does not depend on the
`digital-human` runtime or the browser test page.

## Why

Edge TTS is non-streaming and needs a network round trip per sentence; measured
latency was ~1–6 s per sentence (occasionally >10 s), which dominated the
conversation delay. macOS `say` synthesizes a sentence in ~0.6–1.1 s.

## Run

```bash
my_explorations/local-say-tts/local-say-tts.sh start
my_explorations/local-say-tts/local-say-tts.sh status
my_explorations/local-say-tts/local-say-tts.sh logs
my_explorations/local-say-tts/local-say-tts.sh stop
```

The service listens on `0.0.0.0:8880`; the Docker container reaches it at
`host.docker.internal:8880`.

## 智控台 / CustomTTS config

```text
url:    http://host.docker.internal:8880/tts
method: POST
params: {"input": "{prompt_text}", "voice": "Meijia"}
format: wav
```

The current agent uses `TTS_CustomTTS` / `TTS_CustomTTS0000` (`本地Say-台湾`).
Edge TTS (`TTS_EdgeTTS0001`, `zh-CN-XiaoxiaoNeural`) remains available if you
prefer its quality.

## Voices

```bash
say -v '?' | grep zh
SAY_TTS_VOICE=Tingting my_explorations/local-say-tts/local-say-tts.sh start
SAY_TTS_VOICE=Sinji    my_explorations/local-say-tts/local-say-tts.sh start
```

`Meijia` is Taiwanese, `Tingting` is mainland Mandarin, `Sinji` is Cantonese.

## Notes

- macOS only; uses `/usr/bin/say` and `/usr/bin/afconvert`.
- The service must stay running or `CustomTTS` will fail to connect.
- It does **not** access the microphone.
- For Linux servers, replace `host.docker.internal` with the host LAN IP.
