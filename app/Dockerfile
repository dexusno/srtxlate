# app/Dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl locales tzdata build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /app/templates /app/static

COPY main.py srtxlate.py argos_init.py /app/
COPY templates/index.html /app/templates/
COPY static/style.css /app/static/

# Pre-install Argos model en->nb at build time
RUN python /app/argos_init.py

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
