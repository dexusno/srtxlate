import os
import json
import time
from typing import Dict, Optional, Set

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from srtxlate import translate_srt_with_progress, target_suffix_for_filename, normalize_lang_code

APP_TITLE = "SRT Translator (NLLB-200)"

# Configuration defaults (overridden by .env if present)
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "auto")  # "auto" | "nllb" | "libre" | "argos"
NLLB_ENDPOINT = os.getenv("NLLB_ENDPOINT", "http://nllb:6100")
LIBRE_ENDPOINT = os.getenv("LIBRE_ENDPOINT", "http://libretranslate:5000")
LIBRE_API_KEY = os.getenv("LIBRE_API_KEY", "")

# In-memory progress store for tracking translation progress
# Maps progress_key -> {"total": int, "done": int, "ts": timestamp, "finished": bool}
PROGRESS: Dict[str, Dict[str, float]] = {}
PROGRESS_TTL_SEC = 1800  # 30 minutes TTL for progress entries

app = FastAPI(title=APP_TITLE)

# Mount static directory for assets (e.g., flores200.json for language list)
if not os.path.isdir("static"):
    os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# Load FLORES-200 language list for UI dropdowns
FLORES_LIST = []
FLORES_CODES: Set[str] = set()
FLORES_BY_CODE: Dict[str, str] = {}
def _load_flores_json():
    global FLORES_LIST, FLORES_CODES, FLORES_BY_CODE
    path = os.path.join("static", "flores200.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            FLORES_LIST = json.load(f) or []
        FLORES_CODES = {entry.get("code", "") for entry in FLORES_LIST if entry.get("code")}
        FLORES_BY_CODE = {entry.get("code"): entry.get("name", entry.get("code")) 
                          for entry in FLORES_LIST if entry.get("code")}
    except Exception as exc:
        # If the JSON can't be loaded, we proceed without the list (UI will handle missing list)
        FLORES_LIST = []
        FLORES_CODES = set()
        FLORES_BY_CODE = {}
        print(f"[WARN] Could not load flores200.json: {exc}")

_load_flores_json()

# Helper functions to manage progress tracking
def _set_progress(key: str, total: int, done: int, finished: bool = False) -> None:
    if not key:
        return
    PROGRESS[key] = {
        "total": int(max(total, 0)),
        "done": int(max(min(done, total), 0)),
        "ts": time.time(),
        "finished": bool(finished),
    }

def _get_progress(key: str) -> Optional[Dict[str, float]]:
    return PROGRESS.get(key)

def _gc_progress() -> None:
    """Clean up stale progress entries to free memory."""
    now = time.time()
    stale_keys = [k for k, v in PROGRESS.items() if now - v.get("ts", 0) > PROGRESS_TTL_SEC]
    for k in stale_keys:
        PROGRESS.pop(k, None)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Render the main page template with default settings
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_engine": DEFAULT_ENGINE,
        # Provide any other default values the template might use
        "default_source": "eng_Latn",
        "default_target": "nob_Latn",
    })

# Translation endpoint (synchronous so heavy work runs in threadpool, not on the event loop)
@app.post("/translate")
def translate(
    file: UploadFile = File(...),
    source: str = Form("eng_Latn"),
    target: str = Form("nob_Latn"),
    engine: str = Form("auto"),
    progress_key: str = Form("")
):
    """
    Handle an SRT translation request (multipart form):
      - file: the .srt file to translate
      - source: source language (FLORES code or alias, e.g., 'eng_Latn' or 'en')
      - target: target language (FLORES code or alias, e.g., 'nob_Latn' or 'nb')
      - engine: translation engine ('auto', 'nllb', 'libre', or 'argos')
      - progress_key: unique key to track progress via SSE
    """
    # Normalize input language codes (aliases to FLORES codes)
    source_norm = normalize_lang_code(source)
    target_norm = normalize_lang_code(target)
    if FLORES_CODES:
        # If we have a list of supported codes, validate the requested languages
        if source_norm not in FLORES_CODES:
            raise HTTPException(status_code=400, detail=f"Unsupported source language: {source}")
        if target_norm not in FLORES_CODES:
            raise HTTPException(status_code=400, detail=f"Unsupported target language: {target}")

    # Read and decode the uploaded SRT file
    data = file.file.read()
    srt_in = data.decode("utf-8", errors="replace")

    # Progress callback to update the progress dictionary
    def on_progress(total_lines: int, done_lines: int) -> None:
        _set_progress(progress_key, total_lines, done_lines, finished=False)

    # Initialize progress (so the UI sees 0/0 initially)
    _set_progress(progress_key, 0, 0, finished=False)

    # Perform the translation with progress tracking
    srt_out = translate_srt_with_progress(
        srt_in,
        source=source_norm,
        target=target_norm,
        engine=engine or DEFAULT_ENGINE,
        nllb_endpoint=NLLB_ENDPOINT,
        libre_endpoint=LIBRE_ENDPOINT,
        libre_api_key=LIBRE_API_KEY,
        progress_cb=on_progress,
        batch_size=64,
    )

    # Mark progress as finished
    entry = _get_progress(progress_key) or {}
    total = int(entry.get("total", 0))
    _set_progress(progress_key, total, total, finished=True)

    # Determine output filename (insert target language code before .srt extension)
    original_name = file.filename or "translated.srt"
    base_name = original_name.rsplit(".", 1)[0]
    # Remove any existing trailing language code (e.g. ".en" or ".eng") from base name
    import re as _re
    base_name = _re.sub(r"\.[a-z]{2,3}$", "", base_name, flags=_re.IGNORECASE)
    # Use a short code (ISO 639-1 if available) for target language in filename
    short_code = target_suffix_for_filename(target_norm)
    out_filename = f"{base_name}.{short_code}.srt"

    # Stream the translated SRT back to the client as a file download
    return StreamingResponse(
        iter([srt_out.encode("utf-8")]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{out_filename}"'}
    )

@app.get("/translate_sse")
async def translate_sse(key: str = ""):
    """
    Server-Sent Events (SSE) endpoint for live progress updates.
    Clients can connect to /translate_sse?key=<progress_key> to receive JSON progress objects.
    """
    if not key:
        raise HTTPException(status_code=400, detail="Missing progress key")

    async def event_stream():
        import asyncio, json
        last_done = None
        idle_timeout = time.time() + PROGRESS_TTL_SEC

        # Initial event to ensure the client receives initial zero values
        yield 'data: {"total":0,"done":0,"remaining":0,"finished":false}\n\n'

        # Stream updates until finished or timeout
        while time.time() < idle_timeout:
            _gc_progress()  # cleanup stale entries periodically
            entry = _get_progress(key)
            if entry is None:
                # No progress info yet, wait a bit
                await asyncio.sleep(0.2)
                continue

            total = int(entry.get("total", 0))
            done = int(entry.get("done", 0))
            finished = bool(entry.get("finished", False))
            remaining = max(total - done, 0)

            # Send an update if progress changed or if just finished
            if finished or done != last_done:
                payload = {"total": total, "done": done, "remaining": remaining, "finished": finished}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_done = done

            if finished:
                break  # translation completed

            await asyncio.sleep(0.2)

        # Send a final complete event in case the client connected late or missed the last update
        entry = _get_progress(key) or {"total": 0, "done": 0}
        total = int(entry.get("total", 0))
        done = int(entry.get("done", 0))
        remaining = max(total - done, 0)
        final_payload = {"total": total, "done": done, "remaining": remaining, "finished": True}
        yield f"data: {json.dumps(final_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
