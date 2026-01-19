"""Stream manager for handling multiple noise streams."""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from config import FFmpegConfig
from noise_runner import NoiseFFmpegRunner

logger = logging.getLogger(__name__)


class StreamState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class StreamInfo:
    stream_id: str
    noise_type: str
    runner: NoiseFFmpegRunner
    state: StreamState = StreamState.STOPPED
    started_at: Optional[datetime] = None
    error_message: Optional[str] = None
    hls_path: Optional[str] = None

    def to_dict(self) -> dict:
        runner_status = self.runner.get_status()
        return {
            "stream_id": self.stream_id,
            "noise_type": self.noise_type,
            "state": self.state.value,
            "running": runner_status.get("running", False),
            "pid": runner_status.get("pid"),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error_message": self.error_message,
            "hls_path": self.hls_path,
            "stream_url": f"/hls/{self.stream_id}/stream.m3u8" if self.hls_path else None,
        }

    def health_check(self) -> dict:
        import time
        runner_status = self.runner.get_status()
        is_running = runner_status.get("running", False)
        hls_available = False
        manifest_fresh = False
        if self.hls_path:
            manifest_path = Path(self.hls_path) / "stream.m3u8"
            hls_available = manifest_path.exists()
            if hls_available:
                try:
                    mtime = manifest_path.stat().st_mtime
                    current_time = time.time()
                    manifest_fresh = (current_time - mtime) < 10.0
                except OSError:
                    manifest_fresh = False
        if self.state == StreamState.RUNNING and is_running and hls_available and manifest_fresh:
            status = "healthy"
        elif self.state == StreamState.RUNNING and is_running and hls_available and not manifest_fresh:
            status = "unhealthy"
        elif self.state == StreamState.STOPPED:
            status = "stopped"
        elif self.state == StreamState.STARTING:
            status = "starting"
        else:
            status = "unhealthy"
        return {
            "stream_id": self.stream_id,
            "noise_type": self.noise_type,
            "status": status,
            "process_running": is_running,
            "hls_available": hls_available,
            "manifest_fresh": manifest_fresh,
            "error": self.error_message,
        }


class NoiseStreamManager:
    """Manages multiple noise streams (white, pink, brown)."""

    def __init__(self, base_hls_dir: Path, base_ffmpeg_config: FFmpegConfig, noise_types: list[str]):
        self.base_hls_dir = base_hls_dir
        self.base_ffmpeg_config = base_ffmpeg_config
        self.noise_types = [n.lower() for n in noise_types]
        self._streams: dict[str, StreamInfo] = {}
        self._lock = threading.Lock()

    def get_streams(self) -> dict[str, StreamInfo]:
        with self._lock:
            return dict(self._streams)

    def get_stream(self, stream_id: str) -> Optional[StreamInfo]:
        with self._lock:
            return self._streams.get(stream_id)

    def _create_stream_for_noise(self, noise_type: str) -> StreamInfo:
        stream_id = f"noise_{noise_type}"
        hls_dir = self.base_hls_dir / stream_id
        hls_dir.mkdir(parents=True, exist_ok=True)
        runner = NoiseFFmpegRunner(noise_type, self.base_ffmpeg_config, hls_dir)
        logger.info("Created noise stream: stream_id=%s, type=%s, hls_dir=%s",
                    stream_id, noise_type, hls_dir)
        return StreamInfo(
            stream_id=stream_id,
            noise_type=noise_type,
            runner=runner,
            state=StreamState.STOPPED,
            hls_path=str(hls_dir),
        )

    def start_all_streams(self) -> dict:
        logger.info("Starting all noise streams: %s", ", ".join(self.noise_types))
        results = []
        started_count = 0
        failed_count = 0
        with self._lock:
            for noise in self.noise_types:
                stream_id = f"noise_{noise}"
                if stream_id in self._streams:
                    existing = self._streams[stream_id]
                    if existing.runner.is_running():
                        results.append({"stream_id": stream_id, "status": "already_running", "noise": noise})
                        started_count += 1
                        continue
                stream_info = self._create_stream_for_noise(noise)
                stream_info.state = StreamState.STARTING
                success = stream_info.runner.start()
                if success:
                    stream_info.state = StreamState.RUNNING
                    stream_info.started_at = datetime.now()
                    stream_info.error_message = None
                    started_count += 1
                    results.append({
                        "stream_id": stream_id,
                        "status": "started",
                        "noise": noise,
                        "stream_url": f"/hls/{stream_id}/stream.m3u8",
                    })
                else:
                    stream_info.state = StreamState.ERROR
                    stream_info.error_message = "Failed to start FFmpeg process"
                    failed_count += 1
                    results.append({
                        "stream_id": stream_id,
                        "status": "failed",
                        "noise": noise,
                        "error": stream_info.error_message,
                    })
                self._streams[stream_id] = stream_info
        return {
            "success": started_count > 0,
            "message": f"Started {started_count} streams, {failed_count} failed",
            "total_streams": len(self.noise_types),
            "started": started_count,
            "failed": failed_count,
            "streams": results,
        }

    def stop_all_streams(self) -> dict:
        logger.info("Stopping all noise streams: total=%d", len(self._streams))
        results = []
        stopped_count = 0
        with self._lock:
            for stream_id, stream_info in self._streams.items():
                if stream_info.runner.is_running():
                    success = stream_info.runner.stop()
                    if success:
                        stream_info.state = StreamState.STOPPED
                        stream_info.started_at = None
                        stopped_count += 1
                        results.append({"stream_id": stream_id, "status": "stopped"})
                    else:
                        results.append({"stream_id": stream_id, "status": "failed_to_stop"})
                else:
                    results.append({"stream_id": stream_id, "status": "was_not_running"})
        return {
            "success": True,
            "message": f"Stopped {stopped_count} streams",
            "stopped": stopped_count,
            "streams": results,
        }

    def stop_stream(self, stream_id: str) -> dict:
        with self._lock:
            stream_info = self._streams.get(stream_id)
            if not stream_info:
                return {"success": False, "error": "Stream not found"}
            if not stream_info.runner.is_running():
                return {"success": True, "message": "Stream was not running"}
            success = stream_info.runner.stop()
            if success:
                stream_info.state = StreamState.STOPPED
                stream_info.started_at = None
                return {"success": True, "message": "Stream stopped"}
            else:
                return {"success": False, "error": "Failed to stop stream"}

    def start_stream(self, stream_id: str) -> dict:
        with self._lock:
            stream_info = self._streams.get(stream_id)
            if not stream_info:
                # If not created yet, try to infer noise type from id and create
                if not stream_id.startswith("noise_"):
                    return {"success": False, "error": "Stream not found"}
                noise_type = stream_id.removeprefix("noise_")
                if noise_type not in self.noise_types:
                    return {"success": False, "error": "Invalid noise type"}
                stream_info = self._create_stream_for_noise(noise_type)
                self._streams[stream_id] = stream_info
            if stream_info.runner.is_running():
                return {"success": True, "message": "Stream already running"}
            stream_info.state = StreamState.STARTING
            success = stream_info.runner.start()
            if success:
                stream_info.state = StreamState.RUNNING
                stream_info.started_at = datetime.now()
                stream_info.error_message = None
                return {
                    "success": True,
                    "message": "Stream started",
                    "stream_url": f"/hls/{stream_id}/stream.m3u8",
                }
            else:
                stream_info.state = StreamState.ERROR
                stream_info.error_message = "Failed to start FFmpeg process"
                return {"success": False, "error": "Failed to start stream"}

    def get_status(self) -> dict:
        with self._lock:
            streams_status = [s.to_dict() for s in self._streams.values()]
            running_count = sum(1 for s in self._streams.values() if s.runner.is_running())
            return {
                "total_streams": len(self._streams),
                "running_streams": running_count,
                "stopped_streams": len(self._streams) - running_count,
                "streams": streams_status,
            }

    def health_check(self) -> dict:
        with self._lock:
            stream_health = [s.health_check() for s in self._streams.values()]
            healthy_count = sum(1 for h in stream_health if h["status"] == "healthy")
            stopped_count = sum(1 for h in stream_health if h["status"] == "stopped")
            unhealthy_count = sum(1 for h in stream_health if h["status"] == "unhealthy")
            if unhealthy_count > 0:
                overall_status = "degraded"
            elif healthy_count > 0:
                overall_status = "healthy"
            elif stopped_count == len(stream_health) and stopped_count > 0:
                overall_status = "stopped"
            elif len(stream_health) == 0:
                overall_status = "no_streams"
            else:
                overall_status = "unknown"
            return {
                "status": overall_status,
                "summary": {
                    "total": len(stream_health),
                    "healthy": healthy_count,
                    "stopped": stopped_count,
                    "unhealthy": unhealthy_count,
                },
                "streams": stream_health,
            }
