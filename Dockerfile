# Noise Stream - HLS Audio Streaming using FFmpeg anoisesrc
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with stable uid/gid matching typical host (1000)
RUN groupadd -g 1000 noisestream && \
    useradd --create-home --uid 1000 --gid 1000 --shell /bin/bash noisestream

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create directories for HLS output and config
RUN mkdir -p /app/hls /app/config && \
    chown -R noisestream:noisestream /app

# Switch to non-root user
USER noisestream

# Set environment variables
ENV PYTHONPATH=/app/src \
    HLS_DIR=/app/hls \
    CONFIG_DIR=/app/config \
    HOST=0.0.0.0 \
    PORT=8000 \
    SAMPLE_RATE=44100 \
    AUDIO_BITRATE=128k \
    SEGMENT_TIME=2 \
    LIST_SIZE=5 \
    NOISE_TYPES=white,pink,brown

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
