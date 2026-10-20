# syntax=docker/dockerfile:1
# Ubuntu 24.04 ships Python 3.12, FFmpeg 6.1, espeak-ng, Noto fonts and libraqm in one place.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 MEDIA_ROOT=/data/media PATH=/opt/venv/bin:$PATH

# FFmpeg for rendering, espeak-ng for local placeholder TTS, Noto fonts + libraqm for Devanagari text shaping.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg espeak-ng fonts-noto-core \
       fonts-dejavu-core libraqm0 libfribidi0 libharfbuzz0b ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
ARG INSTALL_DEV=false
RUN pip install -r requirements.txt && if [ "$INSTALL_DEV" = "true" ]; then pip install -r requirements-dev.txt; fi

COPY . .
RUN useradd --create-home --uid 10001 app && mkdir -p /data/media && chown -R app:app /data /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
