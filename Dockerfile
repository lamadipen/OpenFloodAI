# ---------------------------------------------------------------------------
# OpenFloodAI - Multi-stage Dockerfile for edge deployment
# Targets: Raspberry Pi (ARM64), Jetson Nano (ARM64), x86_64
# ---------------------------------------------------------------------------

# Stage 1: Build -----------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy only what the build needs so layer caching works when source changes
# but pyproject.toml does not.
COPY pyproject.toml README.md ./
COPY src/ src/
COPY schemas/ schemas/

RUN pip install --no-cache-dir --prefix=/install .

# Stage 2: Runtime ---------------------------------------------------------
FROM python:3.12-slim

LABEL maintainer="OpenFloodAI Contributors"
LABEL org.opencontainers.image.title="OpenFloodAI"
LABEL org.opencontainers.image.description="Edge-first camera-based river flood detection and warning-support system"
LABEL org.opencontainers.image.source="https://github.com/OpenFloodAI/OpenFloodAI"
LABEL org.opencontainers.image.licenses="MIT"

# System dependencies for opencv-python-headless.
# libgl1 is NOT needed (headless build), but libglib2.0-0 is required at
# runtime for cv2's GLib/GObject usage.
RUN apt-get update && \
    apt-get install -y --no-install-recommends libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN useradd --create-home --shell /bin/bash openflood

# Bring in the installed packages from the builder stage
COPY --from=builder /install /usr/local

# Directories for runtime data (config, alerts, logs).
# Mounted as volumes in production; created here so the paths always exist.
RUN mkdir -p /data/config /data/alerts /data/logs && \
    chown -R openflood:openflood /data

USER openflood
WORKDIR /home/openflood

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import openfloodai; print('ok')"]

ENTRYPOINT ["openfloodai"]
CMD ["--help"]
