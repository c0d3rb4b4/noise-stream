"""Configuration management for noise-stream."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List


def _get_int_env(name: str, default: int, min_val: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        result = int(value)
        if result < min_val:
            return default
        return result
    except ValueError:
        return default


def _get_port_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        result = int(value)
        if result < 1 or result > 65535:
            return default
        return result
    except ValueError:
        return default


@dataclass
class FFmpegConfig:
    """FFmpeg streaming configuration for noise generation."""

    sample_rate: int = field(
        default_factory=lambda: _get_int_env("SAMPLE_RATE", 44100, min_val=8000)
    )
    audio_bitrate: str = field(
        default_factory=lambda: os.getenv("AUDIO_BITRATE", "128k")
    )
    segment_time: int = field(
        default_factory=lambda: _get_int_env("SEGMENT_TIME", 2, min_val=1)
    )
    list_size: int = field(
        default_factory=lambda: _get_int_env("LIST_SIZE", 5, min_val=1)
    )


@dataclass
class AppConfig:
    """Application configuration."""

    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _get_port_env("PORT", 8000))
    hls_dir: Path = field(
        default_factory=lambda: Path(os.getenv("HLS_DIR", "/app/hls"))
    )
    config_dir: Path = field(
        default_factory=lambda: Path(os.getenv("CONFIG_DIR", "/app/config"))
    )
    rabbitmq_url: Optional[str] = field(
        default_factory=lambda: os.getenv("RABBITMQ_URL")
    )
    debug: bool = field(
        default_factory=lambda: os.getenv("DEBUG", "false").lower() == "true"
    )
    log_level: str = field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    noise_types: List[str] = field(
        default_factory=lambda: [s.strip() for s in os.getenv("NOISE_TYPES", "white,pink,brown").split(",") if s.strip()]
    )


@dataclass
class Config:
    """Main configuration container."""

    app: AppConfig = field(default_factory=AppConfig)
    ffmpeg: FFmpegConfig = field(default_factory=FFmpegConfig)


def get_config() -> Config:
    """Get application configuration from environment variables."""
    return Config()
