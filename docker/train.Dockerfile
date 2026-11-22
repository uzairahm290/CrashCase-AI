# Training image: everything `dvc repro` needs, CPU PyTorch. The repo is mounted at /work.
#   docker compose --profile train run --rm train
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[train]"
WORKDIR /work
CMD ["bash", "scripts/reproduce.sh"]
