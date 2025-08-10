# README.md

## SRT → Norwegian Bokmål (nb) Translator

- **Web UI**: Upload `.srt`, get translated `.srt` (timestamps preserved).
- **CLI**: Automate/batch in scripts.
- **Engines**: Local **Argos Translate** (offline) or **LibreTranslate** API (self-hosted).
- **Default target**: `nb` (Norwegian Bokmål).

---

## 1) Requirements

- Docker & Docker Compose **(recommended)**  
  or
- Python 3.11 (for running without Docker)

---

## 2) Quick start (Docker)

1. Put this repo on disk with the structure you see here.
2. Edit `.env` if needed (defaults are fine).
3. Build & run:
   ```bash
   docker compose up -d --build
   ```
4. Open the web UI:  
   [http://localhost:8080/](http://localhost:8080/)

5. Drop a `.srt` file and press **Translate**.  
   You’ll get `<name>.nb.srt`.
