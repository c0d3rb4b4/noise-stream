# Noise Stream

HLS audio streaming of generated noise types (white/pink/brown) using FFmpeg `anoisesrc`, implemented with FastAPI. Structure and endpoints are similar to `livingroom-radio`.

## Features
- Generate and stream white, pink, and brown noise
- HLS output with `.m3u8` playlist and `.ts` segments
- Health monitoring and auto-restart of degraded streams
- Dockerized deployment with `docker-compose`
- Bruno API tests

## Quick Start

### Local Docker

```bash
cd noise-stream
docker compose up --build
```

Service runs on http://localhost:8081

- Health: http://localhost:8081/health
- Status: http://localhost:8081/status
- HLS playlist: http://localhost:8081/hls/noise_white/stream.m3u8

### Configuration
Use `config/app.env.example` or compose environment variables:
- `SAMPLE_RATE` (default `44100`)
- `AUDIO_BITRATE` (default `128k`)
- `SEGMENT_TIME` (default `2`)
- `LIST_SIZE` (default `5`)
- `NOISE_TYPES` (default `white,pink,brown`)

## Endpoints
- `GET /` – Service info
- `GET /health` – Overall health
- `GET /status` – Streams status
- `POST /stream/start` – Start all noise streams
- `POST /stream/stop` – Stop all noise streams
- `GET /stream/{stream_id}` – Stream info (e.g., `noise_white`)
- `GET /stream/{stream_id}/health` – Individual health
- `GET /hls/{stream_id}/{filename}` – Serve HLS files (playlist and segments)

## Development
Install Python deps:
```bash
pip install -r noise-stream/requirements.txt
```
Run locally:
```bash
PYTHONPATH=noise-stream/src uvicorn app:app --host 0.0.0.0 --port 8000
```

## CI/CD (GitHub Actions)
A workflow builds and pushes a Docker image to GHCR when changes are made under `noise-stream/`. Configure repository permissions to allow `GITHUB_TOKEN` push to GHCR.

Image name: `ghcr.io/<owner>/noise-stream:latest`
