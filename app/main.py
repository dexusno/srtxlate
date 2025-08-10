from fastapi import FastAPI, Request, UploadFile, Form
from fastapi.responses import HTMLResponse, StreamingResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import io, os, json, asyncio
from srtxlate import translate_srt
import srt

APP_TITLE = "SRT → Norsk Bokmål"
DEFAULT_SOURCE = os.getenv("DEFAULT_SOURCE", "en")
DEFAULT_TARGET = os.getenv("DEFAULT_TARGET", "nb")
DEFAULT_ENGINE = os.getenv("DEFAULT_ENGINE", "auto")  # auto|argos|libre|ct2
LIBRE_ENDPOINT = os.getenv("LIBRE_ENDPOINT", "http://libretranslate:5000")
LIBRE_API_KEY = os.getenv("LIBRE_API_KEY", None)
CT2_ENDPOINT = os.getenv("CT2_ENDPOINT", "http://ct2:6000")

app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_source": DEFAULT_SOURCE,
        "default_target": DEFAULT_TARGET,
        "default_engine": DEFAULT_ENGINE
    })

@app.post("/translate")
async def translate(
    request: Request,
    file: UploadFile,
    source: str = Form(DEFAULT_SOURCE),
    target: str = Form(DEFAULT_TARGET),
    engine: str = Form(DEFAULT_ENGINE),
):
    if not file.filename.lower().endswith(".srt"):
        return PlainTextResponse("Only .srt files are supported.", status_code=400)

    raw = await file.read()
    out = translate_srt(
        srt_bytes=raw,
        source=source,
        target=target,
        engine=engine,
        libre_endpoint=LIBRE_ENDPOINT,
        libre_api_key=LIBRE_API_KEY,
        ct2_endpoint=CT2_ENDPOINT
    )
    out_name = os.path.splitext(file.filename)[0] + f".{target}.srt"
    return StreamingResponse(io.BytesIO(out), media_type="text/plain; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{out_name}"'})

# ---- SSE progress endpoint ----
@app.post("/translate_sse")
async def translate_sse(
    request: Request,
    file: UploadFile,
    source: str = Form(DEFAULT_SOURCE),
    target: str = Form(DEFAULT_TARGET),
    engine: str = Form(DEFAULT_ENGINE),
):
    if not file.filename.lower().endswith(".srt"):
        return PlainTextResponse("Only .srt files are supported.", status_code=400)

    raw = await file.read()
    text = raw.decode("utf-8-sig", errors="replace")
    items = list(srt.parse(text, ignore_errors=True))

    CHUNK = 64  # items per chunk

    async def event_stream():
        total = len(items)
        out_items = []
        for i in range(0, total, CHUNK):
            batch = items[i:i+CHUNK]
            part_bytes = srt.compose(batch).encode("utf-8")

            translated_bytes = translate_srt(
                srt_bytes=part_bytes,
                source=source,
                target=target,
                engine=engine,
                libre_endpoint=LIBRE_ENDPOINT,
                libre_api_key=LIBRE_API_KEY,
                ct2_endpoint=CT2_ENDPOINT
            )

            t_text = translated_bytes.decode("utf-8", errors="replace")
            t_items = list(srt.parse(t_text, ignore_errors=True))
            out_items.extend(t_items)

            pct = int((i + len(batch)) / max(1, total) * 100)
            yield f"data: {json.dumps({'progress': pct})}\n\n"
            await asyncio.sleep(0)

        # final tick; the UI will make a regular /translate call to download
        yield f"data: {json.dumps({'progress': 100, 'done': True})}\n\n"

    # SSE must be 'text/event-stream' and messages end with \n\n. :contentReference[oaicite:1]{index=1}
    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.get("/healthz")
async def health():
    return {"ok": True}
