"""FastAPI application for serving HLS noise streams (white/pink/brown)."""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response

from config import get_config
from noise_manager import NoiseStreamManager

# Global configuration and stream manager
config = get_config()

# Configure logging from config
log_level = getattr(logging, config.app.log_level.upper(), logging.INFO)
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

stream_manager = NoiseStreamManager(config.app.hls_dir, config.ffmpeg, config.app.noise_types)
_monitor_thread: threading.Thread | None = None
_monitor_running = False


def _monitor_stream_health() -> None:
    global _monitor_running
    while _monitor_running:
        try:
            health = stream_manager.health_check()
            for stream in health.get("streams", []):
                if stream["status"] == "unhealthy" and stream.get("process_running"):
                    stream_id = stream["stream_id"]
                    logger.warning("Noise stream unhealthy; restarting: %s", stream_id)
                    stream_manager.stop_stream(stream_id)
                    stream_manager.start_stream(stream_id)
            # Check every 10 seconds
            for _ in range(10):
                if not _monitor_running:
                    break
                threading.Event().wait(1)
        except Exception as e:
            logger.error("Error in stream health monitor: %s", str(e))
            threading.Event().wait(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _monitor_thread, _monitor_running
    logger.info("Starting noise-stream application")
    config.app.hls_dir.mkdir(parents=True, exist_ok=True)

    _monitor_running = True
    _monitor_thread = threading.Thread(target=_monitor_stream_health, daemon=True)
    _monitor_thread.start()
    logger.info("Started stream health monitoring thread")

    # Auto-start streams on startup
    try:
        result = stream_manager.start_all_streams()
        logger.info(
            "Auto-started noise streams: started=%d, failed=%d, total=%d",
            result.get("started", 0),
            result.get("failed", 0),
            result.get("total_streams", 0),
        )
    except Exception as e:
        logger.error("Auto-start streams failed: %s", str(e), exc_info=True)

    yield

    logger.info("Shutting down noise-stream application")
    _monitor_running = False
    if _monitor_thread:
        _monitor_thread.join(timeout=2)
    stream_manager.stop_all_streams()


app = FastAPI(
    title="Noise Stream",
    description="HLS audio streaming of generated noise (white/pink/brown)",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    status = stream_manager.get_status()
    return {
        "name": "Noise Stream",
        "description": "HLS audio streaming of generated noise (white/pink/brown)",
        "version": "1.0.0",
        "endpoints": {
            "status": "/status",
            "health": "/health",
            "start_all": "POST /stream/start",
            "stop_all": "POST /stream/stop",
            "stream_health": "/stream/{stream_id}/health",
            "stream_hls": "/hls/{stream_id}/stream.m3u8",
        },
        "available_noise": config.app.noise_types,
        "active_streams": status["running_streams"],
        "total_streams": status["total_streams"],
    }


@app.get("/status")
async def status():
    mgr_status = stream_manager.get_status()
    return {
        "hls_dir": str(config.app.hls_dir),
        **mgr_status,
    }


@app.get("/health")
async def health():
    return stream_manager.health_check()


@app.post("/stream/start")
async def start_streams():
    try:
        return stream_manager.start_all_streams()
    except Exception as exc:
        logger.exception("Error starting all streams: %s", exc)
        raise HTTPException(status_code=500, detail=f"Error starting streams: {exc}")


@app.post("/stream/stop")
async def stop_streams():
    return stream_manager.stop_all_streams()


@app.get("/stream/{stream_id}")
async def get_stream_info(stream_id: str):
    stream = stream_manager.get_stream(stream_id)
    if not stream:
        raise HTTPException(status_code=404, detail="Stream not found")
    return stream.to_dict()


@app.get("/stream/{stream_id}/health")
async def get_stream_health(stream_id: str):
    health = stream_manager.health_check()
    for s in health.get("streams", []):
        if s["stream_id"] == stream_id:
            return s
    raise HTTPException(status_code=404, detail="Stream not found")


@app.post("/stream/{stream_id}/start")
async def start_stream(stream_id: str):
    try:
        result = stream_manager.start_stream(stream_id)
        if not result["success"]:
            if result.get("error") == "Stream not found":
                raise HTTPException(status_code=404, detail="Stream not found")
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to start stream"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error starting stream %s: %s", stream_id, exc)
        raise HTTPException(status_code=500, detail=f"Error starting stream: {exc}")


@app.post("/stream/{stream_id}/stop")
async def stop_stream(stream_id: str):
    result = stream_manager.stop_stream(stream_id)
    if not result["success"]:
        if result.get("error") == "Stream not found":
            raise HTTPException(status_code=404, detail="Stream not found")
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to stop stream"))
    return result


@app.get("/hls/{stream_id}/{filename}")
async def get_hls_file(stream_id: str, filename: str):
    if ".." in filename or filename.startswith("/"):
        logger.warning("Invalid filename rejected: %s", filename)
        raise HTTPException(status_code=400, detail="Invalid filename")
    if ".." in stream_id or "/" in stream_id:
        logger.warning("Invalid stream_id rejected: %s", stream_id)
        raise HTTPException(status_code=400, detail="Invalid stream_id")
    file_path = config.app.hls_dir / stream_id / filename
    if not file_path.exists():
        logger.warning("HLS file not found: stream_id=%s, filename=%s", stream_id, filename)
        raise HTTPException(status_code=404, detail="File not found")
    if filename.endswith(".m3u8"):
        media_type = "application/vnd.apple.mpegurl"
        # Read playlist into memory to avoid race condition with FFmpeg updates
        content = file_path.read_bytes()
        # Prevent caching so clients always get fresh playlist
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    elif filename.endswith(".ts"):
        media_type = "video/mp2t"
        return FileResponse(file_path, media_type=media_type)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")


@app.get("/hls/{filename}")
async def get_legacy_hls_file(filename: str):
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    streams = stream_manager.get_streams()
    for stream_id, stream_info in streams.items():
        if stream_info.hls_path:
            file_path = Path(stream_info.hls_path) / filename
            if file_path.exists():
                if filename.endswith(".m3u8"):
                    media_type = "application/vnd.apple.mpegurl"
                    content = file_path.read_bytes()
                    return Response(
                        content=content,
                        media_type=media_type,
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                    )
                elif filename.endswith(".ts"):
                    media_type = "video/mp2t"
                    return FileResponse(file_path, media_type=media_type)
                else:
                    raise HTTPException(status_code=400, detail="Invalid file type")
    raise HTTPException(status_code=404, detail="File not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=config.app.host, port=config.app.port, reload=config.app.debug)
