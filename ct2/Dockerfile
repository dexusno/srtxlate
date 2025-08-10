FROM python:3.11-slim

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    ctranslate2==4.6.0 \
    sentencepiece==0.2.0 \
    transformers==4.42.4 \
    sacremoses==0.1.1 \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6

COPY server.py /srv/server.py

EXPOSE 6000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "6000"]
