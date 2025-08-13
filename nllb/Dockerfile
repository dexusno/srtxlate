FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1

# Torch (CUDA 12.1) + FastAPI stack
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu121 torch && \
    pip install --no-cache-dir fastapi uvicorn[standard] transformers==4.41.2 huggingface_hub==0.23.2

WORKDIR /app
COPY server.py /app/server.py

# IMPORTANT: do NOT bake NLLB_MODEL here. .env controls it.
# Start server (the script contains uvicorn.run)
CMD ["python", "-u", "/app/server.py"]
