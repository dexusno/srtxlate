# CUDA runtime base with NVIDIA libs (works with Docker Desktop + WSL2 GPU)
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/.cache/huggingface

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv build-essential git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Make 'python' and 'pip' available
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1 && \
    update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 1

# Install PyTorch CUDA wheels (CUDA 12.1) + libs
# Official index for CUDA wheels:
# https://pytorch.org/get-started/previous-versions/  (see cu121 instructions)
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu121 \
    torch && \
    pip install --no-cache-dir \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    transformers==4.42.4 \
    sentencepiece==0.2.0

# App
WORKDIR /app
COPY server.py /app/server.py

# Defaults (can be overridden by compose env)
ENV NLLB_DEVICE=cuda \
    NLLB_MODEL=facebook/nllb-200-3.3B \
    NLLB_BATCH_SIZE=32 \
    NLLB_MAX_NEW_TOKENS=256 \
    NLLB_NUM_BEAMS=1

EXPOSE 6100
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "6100"]
