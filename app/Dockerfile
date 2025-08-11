FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (optional but useful for locale/regex performance)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini ca-certificates locales && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code
COPY main.py /app/main.py
COPY srtxlate.py /app/srtxlate.py
COPY templates/ /app/templates/

# Ensure static dir exists and copy assets (flores200.json lives here)
RUN mkdir -p /app/static
COPY static/ /app/static/

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080"]
