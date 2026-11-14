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
params: {"input": "{prompt_text}"}
format: wav
```

Do **not** set `voice` in `params` unless you want to pin one voice; leaving it
out enables automatic routing by text language:

| Text | Voice | Env override |
|---|---|---|
| Contains Chinese | `Yue (Premium)` (`zh_CN`) | `SAY_TTS_VOICE_ZH` |
| Everything else | `Zoe (Premium)` (`en_US`) | `SAY_TTS_VOICE_EN` |

An explicit per-request `voice` field still wins. Setting `SAY_TTS_VOICE`
forces a single voice for all text, e.g. `SAY_TTS_VOICE=Meijia`.

Note: forcing an `en_US` voice on Chinese text produces silence — `say` does
not fall back to another voice.

The current agent uses `TTS_CustomTTS` (自定义语音合成), with `voice` removed from
its params so the service routes by language.
Edge TTS (`TTS_EdgeTTS0001`, `zh-CN-XiaoxiaoNeural`) remains available if you
prefer its quality.

## Voices

```bash
say -v '?' | grep -E 'zh|en_US'
SAY_TTS_VOICE_ZH=Tingting SAY_TTS_VOICE_EN=Samantha my_explorations/local-say-tts/local-say-tts.sh start
```

Installed Chinese voices include `Yue (Premium)` (mainland), `Tingting`
(mainland), `Meijia` (Taiwan), `Sinji` (Cantonese).

## Notes

- macOS only; uses `/usr/bin/say` and `/usr/bin/afconvert`.
- The service must stay running or `CustomTTS` will fail to connect.
- It does **not** access the microphone.
- Mixed Chinese+English sentences use the Chinese voice, which also reads the
  embedded English; the reverse does not work.
- Voice env changes need a `stop`/`start`; the DB config change needs the device
  to reconnect (xiaozhi-server reads agent config on connect).
- For Linux servers, replace `host.docker.internal` with the host LAN IP.
