# noise-stream

## Overview
`noise-stream` is a small, always-on service that generates and serves an **infinite audio noise stream** (white / pink / brown noise) over HTTP. It is designed to be extremely stable for long-running playback on Google Cast devices (Google Home Mini / Nest Mini), treating the stream like internet radio.

The service is intentionally simple and predictable so that another service (for example, `cast-controller`) can reliably re-cast the same URL if playback ever drops.

---

## Design goals
- Infinite stream (no track boundaries)
- Suitable for all-night playback
- LAN-only usage
- Minimal CPU and memory usage
- Simple health checks
- Auto-restart on failure

---

## How it works
The service generates noise in real time and pipes it into an encoder. The encoded audio is served over HTTP as a continuous stream.

Typical pipeline:
- Noise generator: `sox` or `ffmpeg`
- Encoder: `ffmpeg`
- Transport: HTTP streaming

The stream never naturally ends. If the pipeline fails, it is restarted.

---

## Endpoints

### `GET /noise.mp3`
Returns an infinite HTTP audio stream.

**Headers**
- `Content-Type: audio/mpeg`
- `Cache-Control: no-cache`

**Behavior**
- Stream continues until the client disconnects
- Multiple clients may connect simultaneously
- No buffering gaps or track changes

---

### `GET /health`
Health and liveness endpoint.

Returns **200 OK** if:
- HTTP server is running
- Noise generation pipeline is active or restartable

Returns **500** if:
- Streaming pipeline cannot be started
- Service is in a fatal error state

**Example response**
```json
{
  "status": "ok",
  "pipeline": "running",
  "noise": "brown",
  "format": "mp3",
  "uptime_s": 86400
}
```

---

### `GET /metrics` (optional)
Prometheus-style metrics.

Suggested metrics:
- `noise_stream_clients`
- `noise_stream_bytes_sent_total`
- `noise_stream_pipeline_restarts_total`

---

## Configuration

Environment variables:

| Variable | Description | Default |
|--------|-------------|---------|
| `NOISE_COLOR` | `white`, `pink`, or `brown` | `brown` |
| `FORMAT` | `mp3` or `aac` | `mp3` |
| `BITRATE` | Audio bitrate | `128k` |
| `SAMPLE_RATE` | Sample rate | `44100` |
| `CHANNELS` | `1` (mono) or `2` (stereo) | `1` |
| `PORT` | HTTP port | `8000` |
| `LOG_LEVEL` | Logging level | `info` |

---

## Docker behavior
- Pipeline starts on container boot
- HTTP server listens on `PORT`
- Designed to run continuously
- Container should restart automatically on failure

Recommended Docker options:
- `restart: unless-stopped`
- Healthcheck hitting `/health`

---

## Implementation notes

### Noise generation
Examples:
- White noise: `sox -n -t wav - synth whitenoise`
- Brown noise: `sox -n -t wav - synth brownnoise`
- Pink noise: `sox -n -t wav - synth pinknoise`

### Encoding
Use `ffmpeg` to encode to MP3:
```
ffmpeg -f wav -i pipe:0 -f mp3 -b:a 128k pipe:1
```

### Restart strategy
- If the pipeline crashes:
  - Log the failure
  - Restart with exponential backoff
  - Increment restart counters
- The HTTP server should remain up even while the pipeline restarts

---

## Operational guidance
- Keep this service always running, even when not actively playing
- Avoid stopping the container between uses
- LAN-only exposure is strongly recommended

---
