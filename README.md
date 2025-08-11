# srtxlate — Multi‑Language SRT Translator (NLLB‑200)

Translate subtitle **.srt** files between **200+ languages** in your browser (drag‑and‑drop) or via a simple **HTTP API** you can script with `curl`.  
Quality is provided by **Meta’s NLLB‑200** models through Hugging Face Transformers; LibreTranslate/Argos remain as fallbacks.  
Everything runs in Docker for easy local use and server deployment.

- **Preserves timestamps and formatting**
- **Full FLORES‑200 language list** in the UI (loaded from `app/static/flores200.json`)
- **GPU acceleration** (NVIDIA) or **CPU** baseline
- **Live progress** via SSE (lines done / total)
- **Clean filenames** (e.g., `...Episode 3.eng.srt` → `...Episode 3.nb.srt`)

> NLLB‑200 requires setting the **forced BOM token** based on FLORES codes (e.g., `eng_Latn`). No manual model conversion is needed—everything happens automatically within Docker.


---

## Contents

- [Architecture](#architecture)
- [Quick start (GUI)](#quick-start-gui)
- [Headless/Server use with curl](#headlessserver-use-with-curl)
- [Configuration](#configuration)
- [GPU vs CPU](#gpu-vs-cpu)
- [Language list & filenames](#language-list--filenames)
- [Troubleshooting](#troubleshooting)
- [Credits & licensing](#credits--licensing)
- [Development notes](#development-notes)

---

## Architecture

Compose services:

- **app** — FastAPI backend + minimal web UI (drag & drop, language dropdowns, progress SSE)
- **nllb** — Transformers service running an NLLB‑200 model (downloads on first run; cached in a Docker volume)
- **libretranslate** — optional fallback API (Argos‑Translate based)

Data flow:

- `app` → `nllb` via HTTP (`POST /translate`) for **batched** line translation  
- UI listens to `GET /translate_sse?key=...` for **progress events**

**Model conversion?** None needed. We use the PyTorch models from Huggingface directly; the container downloads them on demand. No CT2/ONNX conversion is required for this setup.

---

## Quick start (GUI)

### Prereqs

- **Docker Desktop** (Windows/macOS) or **Docker Engine** (Linux)
- For **GPU on Windows**, Docker Desktop using **WSL2** with GPU support enabled
- For **GPU on Linux**, install **NVIDIA Container Toolkit**

### 1) Clone

```bash
git clone https://github.com/dexusno/srtxlate.git
cd srtxlate
```

### 2) Check `.env`

```ini
DEFAULT_SOURCE=en
DEFAULT_TARGET=nb
DEFAULT_ENGINE=auto
NLLB_ENDPOINT=http://nllb:6100
LIBRE_ENDPOINT=http://libretranslate:5000
LIBRE_API_KEY=
```

### 3) Build & run (CPU or GPU — see GPU section below)

```bash
docker compose up -d --build
```

Open the UI: **http://localhost:8080**

- Drop an `.srt`, pick **Source** / **Target** by **name**, choose engine (Auto is fine), click **Translate**.
- Progress updates (“Lines: X/Y processed”) stream during the job.
- Click **Download translated .srt** when it’s ready.

> The first translation triggers a one‑time model download in the `nllb` container (several GB, depending on model). Subsequent runs reuse the cache.

---

## Headless/Server use with curl

Use the HTTP API from any machine with `curl` — no Python required.

**Translate (multipart):**

```
POST /translate
Fields:
  file         = .srt file (multipart form field)
  source       = FLORES code or alias (e.g., eng_Latn or en)
  target       = FLORES code or alias (e.g., nob_Latn or nb)
  engine       = auto | nllb | libre | argos
  progress_key = any unique string (UUID) to correlate SSE progress
Response:
  Content-Type: application/octet-stream
  Content-Disposition: attachment; filename="<cleaned>.xx.srt"
```

**Progress SSE (optional):**
```
GET /translate_sse?key=<progress_key>
data: {"total": N, "done": M, "remaining": N-M, "finished": true|false}
```

**Example — Linux/macOS:**
```bash
uuid=$(uuidgen)
curl -sS -o out.nb.srt -D headers.txt   -F "file=@input.eng.srt"   -F "source=eng_Latn"   -F "target=nob_Latn"   -F "engine=nllb"   -F "progress_key=$uuid"   http://localhost:8080/translate
```

**Example — Windows PowerShell:**
```powershell
$uuid = [guid]::NewGuid().ToString()
curl http://localhost:8080/translate `
  -F "file=@input.eng.srt" `
  -F "source=eng_Latn" `
  -F "target=nob_Latn" `
  -F "engine=nllb" `
  -F "progress_key=$uuid" `
  -o out.nb.srt -D headers.txt
```

**Batch a folder (PowerShell):**
```powershell
$src = "eng_Latn"; $tgt = "nob_Latn"
Get-ChildItem -Path . -Filter *.srt | ForEach-Object {
  $uuid = [guid]::NewGuid().ToString()
  $in = $_.FullName
  $out = ($_.BaseName -replace '\.[a-z]{2,3}$','') + ".nb.srt"
  curl http://localhost:8080/translate `
    -F "file=@$in" -F "source=$src" -F "target=$tgt" -F "engine=nllb" -F "progress_key=$uuid" `
    -o $out | Out-Null
}
```

---

## Configuration

### Language list (UI)

- The UI reads `app/static/flores200.json` to populate **all languages by name**.  
  Format (**array** of objects):
  ```json
  [
    { "name": "English", "code": "eng_Latn" },
    { "name": "Norwegian Bokmål", "code": "nob_Latn" }
  ]
  ```
- There is a complete list of supported languages in the flores200.json file provided.
- If you customize the list, rebuild the **app** image or bind‑mount `app/static` during development.

### Engine routing

- **auto** → NLLB → LibreTranslate → Argos (first healthy wins)
- **nllb** → only the NLLB service
- **libre** → only LibreTranslate (Argos backend)

### Environment variables

From `.env`:
- `DEFAULT_SOURCE`, `DEFAULT_TARGET` — defaults in the UI
- `DEFAULT_ENGINE` — `auto` recommended
- `NLLB_ENDPOINT` — where the NLLB microservice listens
- `LIBRE_ENDPOINT`, `LIBRE_API_KEY` — LibreTranslate settings (optional)

---

## GPU vs CPU

### Windows (Docker Desktop + WSL2)
- Enable GPU in Docker Desktop Settings (WSL2 backend).
- Verify from the container:
  ```powershell
  docker compose exec nllb nvidia-smi
  curl http://localhost:6100/healthz   # should report "device":"cuda"
  ```

### Linux
- Install **NVIDIA Container Toolkit**.
- Start with GPU override:
  ```bash
  docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
  ```

### Compose notes
- This repo includes `docker-compose.gpu.yml` which adds `gpus: all` and a few CUDA‑friendly envs.
- Older Compose engines can use the `deploy.resources.reservations.devices` form (see Docker docs).

**Performance tips**
- NLLB batches lines (default 64). GPU yields large speed‑ups on medium/large SRTs.
- First call downloads the model into the container’s cache volume; reuses afterwards.
- CPU mode is fine for non‑urgent or automated overnight jobs.

---

## Language list & filenames

- Requests accept **FLORES codes** (`eng_Latn`, `nob_Latn`, …) and common **aliases** (`en`, `nb`, …).  
- Output filenames prefer **ISO‑639‑1** when obvious (`nb`, `en`, `de`, …). When no 2‑letter code exists, we fall back to the **3‑letter** part of the FLORES code.  
- If the input ends with `.xx` or `.xxx` (e.g., `.eng`), the app **removes** it and appends the new target code (e.g., `.nb`).

---

## Troubleshooting

- **UI shows only a couple of languages**  
  Ensure `app/static/flores200.json` exists in the image. Rebuild without cache:
  ```bash
  docker compose build --no-cache app && docker compose up -d app
  ```
  Check from host: `curl http://localhost:8080/static/flores200.json`

- **Model download looks stuck on first run**  
  It’s a large download. Watch: `docker compose logs -f nllb`. When done, `/healthz` responds.

- **GPU not used**  
  - Windows: confirm WSL2 backend and GPU enabled in Docker Desktop.
  - Linux: install NVIDIA Container Toolkit; launch with `gpus: all`.
  - Inside `nllb`: `nvidia-smi` should show your GPU.

- **High CPU use / UI sluggish**  
  Use GPU. On Windows/WSL2, you can also cap WSL resources via `.wslconfig`.

---

## Credits & licensing

This project orchestrates and depends on several open‑source components. Please review and comply with their licenses:

- **Meta NLLB‑200 models** — CC‑BY‑NC 4.0 ([model card](https://huggingface.co/facebook/nllb-200-distilled-600M))  
- **FLORES‑200 dataset/codes** — CC‑BY‑SA 4.0 ([GitHub repo](https://github.com/facebookresearch/flores))  
- **LibreTranslate** — AGPL‑3.0 ([project page](https://github.com/LibreTranslate/LibreTranslate))  
- **Argos Translate** — MIT / CC0 dual license ([repo](https://github.com/argosopentech/argos-translate))

**Your content**: Requests and translated outputs are yours; software licenses above apply to code/models, not your subtitle text. If you modify/redistribute the fallback services (e.g., LibreTranslate), the AGPL terms apply to those modifications.

---

## Development notes

- The UI and static assets live under `app/templates` and `app/static`. During active development you can bind‑mount them to avoid rebuilds:
  ```yaml
  services:
    app:
      volumes:
        - ./app/templates:/app/templates:ro
        - ./app/static:/app/static:ro
  ```
- To switch NLLB models, edit the `nllb` service image/config; the container will download the specified model on first use.

---

Happy translating. The world is large; your subtitles should be too.
