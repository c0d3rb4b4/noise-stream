"""FFmpeg process runner for HLS audio streaming using anoisesrc."""

import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from config import FFmpegConfig

logger = logging.getLogger(__name__)


class NoiseFFmpegRunner:
    """Manages FFmpeg process for HLS audio streaming from generated noise."""

    def __init__(self, noise_type: str, config: FFmpegConfig, hls_dir: Path):
        """Initialize FFmpeg runner.

        Args:
            noise_type: One of 'white', 'pink', 'brown'.
            config: FFmpeg configuration settings.
            hls_dir: Directory to output HLS segments.
        """
        self.noise_type = noise_type.lower()
        self.config = config
        self.hls_dir = hls_dir
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stderr_thread: Optional[threading.Thread] = None
        self._last_error: Optional[str] = None

    def _read_stderr(self) -> None:
        if not self._process or not self._process.stderr:
            return
        try:
            for line in iter(self._process.stderr.readline, b""):
                if not line:
                    break
                decoded_line = line.decode("utf-8", errors="replace").strip()
                if "error" in decoded_line.lower():
                    logger.error("FFmpeg error: %s", decoded_line)
                    self._last_error = decoded_line
                elif "warning" in decoded_line.lower():
                    logger.warning("FFmpeg warning: %s", decoded_line)
        except Exception as e:
            logger.error("Error reading FFmpeg stderr: %s", str(e))

    def _build_command(self) -> list[str]:
        """Build FFmpeg command for HLS streaming from generated noise."""
        output_path = self.hls_dir / "stream.m3u8"
        segment_path = self.hls_dir / "segment%03d.ts"

        # anoisesrc supports color=white|pink|brown
        source = f"anoisesrc=color={self.noise_type}:sample_rate={self.config.sample_rate}"

        command = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", source,
            "-c:a", "aac",
            "-b:a", self.config.audio_bitrate,
            "-f", "hls",
            "-hls_time", str(self.config.segment_time),
            "-hls_list_size", str(self.config.list_size),
            "-hls_flags", "delete_segments",
            "-hls_segment_filename", str(segment_path),
            str(output_path),
        ]
        logger.debug(
            "Built FFmpeg command: noise=%s, sample_rate=%d, bitrate=%s, segment_time=%d, list_size=%d, output=%s",
            self.noise_type, self.config.sample_rate, self.config.audio_bitrate,
            self.config.segment_time, self.config.list_size, output_path,
        )
        return command

    def start(self) -> bool:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                logger.warning("FFmpeg process already running: pid=%d, noise=%s",
                               self._process.pid, self.noise_type)
                return False

            self.hls_dir.mkdir(parents=True, exist_ok=True)
            ffmpeg_path = shutil.which("ffmpeg")
            if not ffmpeg_path:
                logger.error("FFmpeg not found in PATH")
                return False

            cmd = self._build_command()
            logger.info("Starting FFmpeg process: noise=%s, hls_dir=%s",
                        self.noise_type, self.hls_dir)
            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
                self._stderr_thread.start()
                self._last_error = None
                return True
            except FileNotFoundError:
                logger.error("FFmpeg executable not found", exc_info=True)
                return False
            except subprocess.SubprocessError as e:
                logger.error("Failed to start FFmpeg process: noise=%s, error=%s",
                             self.noise_type, str(e), exc_info=True)
                return False

    def stop(self) -> bool:
        with self._lock:
            if self._process is None:
                logger.warning("No FFmpeg process to stop")
                return False
            if self._process.poll() is not None:
                self._process = None
                return True
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None
            return True

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def get_status(self) -> dict:
        with self._lock:
            if self._process is None:
                return {"running": False, "pid": None}
            poll_result = self._process.poll()
            if poll_result is not None:
                return {"running": False, "pid": None, "exit_code": poll_result, "error": self._last_error}
            return {"running": True, "pid": self._process.pid, "error": self._last_error}
