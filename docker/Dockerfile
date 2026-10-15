# Multi-stage build. One image runs both the API and the worker (different commands).
#   docker build -f docker/Dockerfile -t crashcase .                      # light, stub models
#   docker build -f docker/Dockerfile --build-arg INSTALL_ML=true -t crashcase:ml .   # YOLO + CLIP

FROM python:3.11-slim AS builder
ARG INSTALL_ML=false
# Extra optional dependency groups, e.g. "flows" for the Prefect runner image
ARG EXTRAS=""
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && if [ "$INSTALL_ML" = "true" ]; then \
      /opt/venv/bin/pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
      && /opt/venv/bin/pip install ".[ml${EXTRAS:+,$EXTRAS}]"; \
    else \
      /opt/venv/bin/pip install ".${EXTRAS:+[$EXTRAS]}"; \
    fi

FROM python:3.11-slim AS runtime
# libgl/libglib are needed by OpenCV inside ultralytics; harmless for the light image.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY configs ./configs
COPY scripts ./scripts
COPY training ./training
COPY serving ./serving
COPY params.yaml dvc.yaml ./
RUN mkdir -p /app/data/uploads /app/models && chown -R app:app /app
USER app
EXPOSE 8000 9100
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:8000/health || exit 1
CMD ["uvicorn", "crashcase.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
