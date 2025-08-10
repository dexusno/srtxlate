> [!WARNING]
**Experimental — work in progress.**
This project is under active development and is **not ready for production use**. Expect instability, incomplete features, and frequent changes.

# srtxlate

A subtitle (`.srt`) translation suite combining Argos Translate, LibreTranslate, and CTranslate2. Designed for web UI drag‑and‑drop and CLI automation.

**Current goal**: Offer easy `.srt` subtitle translation preserving timecodes, formatting, and structure. Multiple engines are supported, and everything is containerized with Docker.

---

## Features (Work‑In‑Progress)

-  **Web UI**: Drag-and-drop subtitle translation interface  
-  **CLI**: Automate batch translations  
-  Supported backends:
  -  **Argos Translate** (offline)
  -  **LibreTranslate** (self-hosted API)
  -  **CTranslate2 / Marian** (experimental backend)  
-  Cleanly handles `.srt` formatting and inline tags (e.g., `<i>`, `<b>`)  
-  Dockerized stack — spin everything up with a single command

---

## Quickstart

```bash
git clone https://github.com/you/srtxlate.git
cd srtxlate

# Optional: override defaults
echo -e "DEFAULT_SOURCE=en
DEFAULT_TARGET=nb
DEFAULT_ENGINE=auto
LIBRE_ENDPOINT=http://libretranslate:5000" > .env

docker compose up -d
```

Access the web UI at `http://localhost:8080/` once services are running.

---

## Project Structure

```
srtxlate/
├── app/            # Web UI (FastAPI) and UI assets
├── cli/            # Command-line translation tool
├── ct2/            # CTranslate2 Marian backend (experimental)
├── models/         # Place Marian/OPUS models here
├── docker-compose.yml
├── .env            # Configuration overrides
└── README.md
```

---

## Why "srtxlate"?

People want subtitle translation that’s both accurate and retains structure. Current tools feel either too manual, too fragmented, or overkill. Combining Argos, LibreTranslate, and CTranslate2 gives you flexibility, especially in offline scenarios—but the pipeline is still unstable and highly experimental.

---

## Next Steps & Contribution Ideas

- Refine quality for CTranslate2 Marian translations  
- Improve the UI experience (download buttons, progress feedback)  
- Add GPU/CUDA support for performance  
- Handle corner cases in `.srt` parsing: multiline tags, captions with music cues, etc.  
- Streamline multilingual models setup

---

## License

MIT — no warranty. Use at your own risk, especially since it’s experimental right now.

---

Thanks for checking this out. Feedback, issues, and PRs are appreciated, especially around making the translation quality more reliable or the interface more user‑friendly.
