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

DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "auto")  # auto|nllb|libre|argos
NLLB_ENDPOINT = os.getenv("NLLB_ENDPOINT", "http://nllb:6100")
LIBRE_ENDPOINT = os.getenv("LIBRE_ENDPOINT", "http://libretranslate:5000")
LIBRE_API_KEY = os.getenv("LIBRE_API_KEY", "")

# In-memory progress store: { key: {"total": int, "done": int, "ts": float, "finished": bool} }
PROGRESS: Dict[str, Dict[str, float]] = {}
PROGRESS_TTL_SEC = 1800  # 30 min

app = FastAPI(title=APP_TITLE)

# Mount static so the browser can fetch /static/flores200.json
if not os.path.isdir("static"):
    os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# ---- Load FLORES-200 list (name + code) for validation/defaults ----
FLORES_LIST = []
FLORES_CODES: Set[str] = set()
FLORES_BY_CODE: Dict[str, str] = {}  # code -> display name

def _load_flores_json() -> None:
    global FLORES_LIST, FLORES_CODES, FLORES_BY_CODE
    path = os.path.join("static", "flores200.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            FLORES_LIST = json.load(f) or []
        FLORES_CODES = {e.get("code", "") for e in FLORES_LIST if e.get("code")}
        FLORES_BY_CODE = {e.get("code"): e.get("name", e.get("code")) for e in FLORES_LIST if e.get("code")}
    except Exception as exc:
        # Keep running even if the JSON is missing; UI will fail to load it, but API can still work.
        FLORES_LIST = []
        FLORES_CODES = set()
        FLORES_BY_CODE = {}
        print(f"[WARN] Could not load static/flores200.json: {exc}")

_load_flores_json()


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
    now = time.time()
    stale = [k for k, v in PROGRESS.items() if now - v.get("ts", 0) > PROGRESS_TTL_SEC]
    for k in stale:
        PROGRESS.pop(k, None)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_engine": DEFAULT_ENGINE,
            # Optionally expose defaults the page might want to know
            "default_source": "eng_Latn",
            "default_target": "nob_Latn",
        },
    )


# Synchronous so FastAPI runs it in a threadpool; leaves event loop free for SSE.
@app.post("/translate")
def translate(  # def (not async def)
    file: UploadFile = File(...),
    # UI will send FLORES codes directly (e.g., "eng_Latn" -> "nob_Latn")
    # but we also accept simple aliases ("en", "nb") and normalize.
    source: str = Form("eng_Latn"),
    target: str = Form("nob_Latn"),
    engine: str = Form("auto"),
    progress_key: str = Form(""),
):
    """
    Multipart:
      - file: .srt
      - source: FLORES code (e.g., 'eng_Latn') or alias ('en')
      - target: FLORES code (e.g., 'nob_Latn') or alias ('nb')
      - engine: 'auto' | 'nllb' | 'libre' | 'argos'
      - progress_key: UUID from browser to correlate SSE
    """
    # Normalize incoming codes to FLORES if possible (en->eng_Latn; nb->nob_Latn)
    source_norm = normalize_lang_code(source)
    target_norm = normalize_lang_code(target)

    # If our FLORES list loaded, optionally validate
    if FLORES_CODES:
        if source_norm not in FLORES_CODES:
            raise HTTPException(status_code=400, detail=f"Unsupported source language: {source}")
        if target_norm not in FLORES_CODES:
            raise HTTPException(status_code=400, detail=f"Unsupported target language: {target}")

    # Read the uploaded SRT
    data = file.file.read()
    srt_in = data.decode("utf-8", errors="replace")

    # Progress callback from translator
    def on_progress(total_lines: int, done_lines: int) -> None:
        _set_progress(progress_key, total_lines, done_lines, finished=False)

    # Initialize so SSE shows something immediately
    _set_progress(progress_key, 0, 0, finished=False)

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

    # Mark finished
    entry = _get_progress(progress_key) or {}
    total = int(entry.get("total", 0))
    _set_progress(progress_key, total, total, finished=True)

    # Compute output filename
    in_name = file.filename or "translated.srt"
    base = in_name.rsplit(".", 1)[0]

    # strip existing trailing language suffix .xx or .xxx if present
    import re as _re
    base = _re.sub(r"\.[a-z]{2,3}$", "", base, flags=_re.IGNORECASE)

    short = target_suffix_for_filename(target_norm)  # prefer ISO-639-1 where known
    out_name = f"{base}.{short}.srt"

    return StreamingResponse(
        iter([srt_out.encode("utf-8")]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@app.get("/translate_sse")
async def translate_sse(key: str = ""):
    """
    Streams JSON progress via SSE:
      data: {"total":N,"done":M,"remaining":N-M,"finished":bool}\n\n
    """
    if not key:
        raise HTTPException(status_code=400, detail="Missing progress key")

    async def gen():
        import asyncio, json
        last_done = None
        idle_deadline = time.time() + PROGRESS_TTL_SEC

        # Initial JSON so UI shows counters even for very fast jobs
        yield 'data: {"total":0,"done":0,"remaining":0,"finished":false}\n\n'

        while time.time() < idle_deadline:
            _gc_progress()
            entry = _get_progress(key)
            if entry is None:
                await asyncio.sleep(0.2)
                continue

            total = int(entry.get("total", 0))
            done = int(entry.get("done", 0))
            finished = bool(entry.get("finished", False))
            remaining = max(total - done, 0)

            if finished or done != last_done:
                payload = {"total": total, "done": done, "remaining": remaining, "finished": finished}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_done = done

            if finished:
                break

            await asyncio.sleep(0.2)

        # Final JSON (in case the UI connected late)
        entry = _get_progress(key) or {"total": 0, "done": 0}
        total = int(entry.get("total", 0))
        done = int(entry.get("done", 0))
        remaining = max(total - done, 0)
        final_payload = {"total": total, "done": done, "remaining": remaining, "finished": True}
        import json as _json
        yield f"data: {_json.dumps(final_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
