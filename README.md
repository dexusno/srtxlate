# srtxlate — Multi‑Language Subtitle (.SRT) Translator (NLLB‑200)

Translate `.srt` subtitle files between **200+ languages** via a minimal **web UI** (drag‑and‑drop) or a scriptable **HTTP API**.  
Quality is provided by **Meta’s NLLB‑200** models through Hugging Face Transformers; **LibreTranslate/Argos** remains an optional fallback.  
Everything runs in **Docker** for easy local use and server deployment. Works **offline** once models are cached or provided locally.

- **Preserves timestamps and formatting**
- **Merges multi‑line subtitle entries** for better context → splits back on output
- **Fixes split‑word artifacts** (e.g., `ikk\ne` → `ikke`)
- **Handles ALL‑CAPS scene/sound descriptions** correctly
- **Full FLORES‑200 language list** in the UI (`app/static/flores200.json`)
- **GPU acceleration** (NVIDIA) or **CPU** baseline
- **Live progress** via SSE (lines done / total)
- **Clean filenames** (`...Episode 3.eng.srt` → `...Episode 3.nb.srt`)
- **Interactive setup** (`setup.ps1`) for build/start/health checks
- **Local model support** (`MODEL_DIR`) with `local_files_only=True`
- **/healthz** exposes model/device state from each service

> **NLLB‑200 note:** We set the **forced BOS token** from FLORES codes (e.g., `eng_Latn`). No manual model conversion is required; PyTorch models are pulled from Hugging Face on first run, or loaded locally if present in `MODEL_DIR`.

---

## Contents

- [Architecture](#architecture)
- [Quick start (GUI)](#quick-start-gui)
- [Headless/Server: curl](#headlessserver-curl)
- [Interactive setup (PowerShell)](#interactive-setup-powershell)
- [Local model support](#local-model-support)
- [/healthz & health.ps1](#healthz--healthps1)
- [Configuration (.env)](#configuration-env)
- [GPU vs CPU](#gpu-vs-cpu)
- [Language list & filenames](#language-list--filenames)
- [Troubleshooting](#troubleshooting)
- [Credits & licensing](#credits--licensing)
- [Development notes](#development-notes)

---

## Architecture

**Compose services**

- **app** — FastAPI backend + minimal web UI (drag & drop, language dropdowns, progress SSE)
- **nllb** — Transformers service running an NLLB‑200 model (downloads on first use; cached in a Docker volume or read from `MODEL_DIR`)
- **libretranslate** — optional fallback API (Argos‑Translate based)

**Workflow**

1. Browser uploads `.srt`. The **app** merges all lines within a subtitle index for better context.
2. **app → nllb**: batched translation via `POST /translate`.
3. **Progress** flows back to the browser via `GET /translate_sse?key=...`.
4. On return, **app** splits the merged content back into original line structure, fixes split‑word artifacts, preserves formatting, and writes a clean output filename.

**Model conversion**: none. We use Hugging Face PyTorch models directly.

---

## Quick start (GUI)

### Prereqs

- **Docker Desktop** (Windows/macOS) or **Docker Engine** (Linux)
- For **GPU on Windows**, Docker Desktop with **WSL2 GPU** support enabled
- For **GPU on Linux**, install **NVIDIA Container Toolkit**

### 1) Clone Repo

```bash
git clone https://github.com/dexusno/srtxlate.git
cd srtxlate
```

### 2) Run setup

Use the interactive PowerShell menu (Windows/PowerShell). It builds/starts services and can run health checks.

Windows:
```powershell
./setup.ps1
```

Linux:
```bash
./setup.sh
```
The setup script is menu driven.  
1. Download the model(s) you want to use and edit the .env file to reflect the active model (default is nllb-200-distilled-600M, the smallest one)  
2. Pick **2 for GPU** or **3 for CPU** as appropriate (see next section).  

Docker will complete the setup, downloading all dependencies and start the server, then revert to the menu where you can then  
3. Run healt checks to confirm everything is up and running.

1. **Download models only** — caches model(s) locally without starting services.
2. **Build & Start GPU stack** — uses `docker-compose.gpu.yml` (CUDA).
3. **Build & Start CPU stack** — uses default `docker-compose.yml`.
4. **Start GPU stack (no rebuild)** - for running last stack without changes.
5. **Start CPU stack (no rebuild)** - for running last stack without changes.
6. **Run health checks** — uses `health.ps1` to verify endpoints and show model/device info.
7. **Exit**.

**Notes**

- `.env` controls defaults. You can easily choose witch model to run by editing it. (model id/path, endpoints, batching).
- If `MODEL_DIR` already contains the model, it will be used with `local_files_only=True` (no re‑download).

---

## Local model support

To run fully **offline** after the first download:

1. Download NLLB‑200 to a local path (via option 1 in `setup.ps1` or manually).
2. Set `MODEL_DIR=/absolute/path/to/model` in `.env`.
3. Start with option **4** (GPU) or **5** (CPU) to reuse the local model.

When `MODEL_DIR` is set, the **nllb** service loads from disk only.

---

## /healthz & health.ps1

The **nllb** service exposes `/healthz` with extended diagnostics, for example:

```json
{
  "ok": true,
  "configured_model": "facebook/nllb-200-3.3B",
  "configured_model_dir": "/models/nllb",
  "loaded_model": "facebook/nllb-200-3.3B",
  "device": "cuda",
  "cuda_available": true
}
```

Run the consolidated checkers:

```powershell
./health.ps1 - Windows Powershell
./health.sh - Linux
```

It queries **app**, **libretranslate**, and **nllb**, reporting service reachability plus: device (`cpu`/`cuda`), configured model + dir, loaded model, and CUDA availability.  
**You can also run health checks from the setup script.**

---

Then open: <http://localhost:8080>

---  
## Usage of the simple web interface
- Drop an `.srt`, pick **Source** / **Target** language, choose engine (Auto is fine), click **Translate**.
- Progress updates (“Lines: X/Y processed”) stream during the job.
- Click **Download translated .srt** when it’s ready.

---
## Headless / Server Usage with `curl`

Use the HTTP API from any machine with `curl`. No Python client needed.

**Base URL (default):** `http://localhost:8080`

---

## 1) What you send

`POST /translate` (multipart form)

| Field        | Required | Example            | Notes |
|--------------|----------|--------------------|-------|
| `file`       | yes      | `@input.eng.srt`   | The `.srt` file to translate. |
| `source`     | yes      | `eng_Latn` or `en` | Source language — FLORES-200 code or alias. |
| `target`     | yes      | `nob_Latn` or `nb` | Target language — FLORES-200 code or alias. |
| `engine`     | no       | `nllb`             | One of: `auto`, `nllb`, `libre`, `argos`. |
| `progress_key` | no     | UUID string        | Include if you want live progress via SSE. |

**Response:** translated SRT as a file download.  
Headers include e.g. `Content-Type: application/octet-stream` and  
`Content-Disposition: attachment; filename="<original>.<languagecode>.srt"`.

> **Filename suffix:** The server derives a short code from the target. For Norwegian Bokmål you will typically get `nob`, so the filename ends with `.nob.srt`. You can always override the name locally with `-o` in `curl`.

---

## 2) Live progress (optional)

`GET /translate_sse?key=<progress_key>`

Server‑Sent Events stream JSON payloads like:

```json
{"total": 0, "done": 0, "remaining": 0, "finished": false}   // initial
{"total": 123, "done": 48, "remaining": 75, "finished": false}
...
{"total": 123, "done": 123, "remaining": 0, "finished": true}
```

> `key` is **required** on the SSE endpoint. If you omit `progress_key` on `/translate`, the job still runs, but SSE won’t have a key to follow.

---

## 3) Quick examples

### Linux / macOS (bash)

```bash
uuid=$(uuidgen)
curl -sS -D headers.txt -o out.nob.srt   -F "file=@input.eng.srt"   -F "source=eng_Latn"   -F "target=nob_Latn"   -F "engine=nllb"   -F "progress_key=$uuid"   http://localhost:8080/translate &

# (optional) watch progress
curl -N http://localhost:8080/translate_sse?key="$uuid"
```

### Windows PowerShell

```powershell
$uuid = [guid]::NewGuid().ToString()
curl http://localhost:8080/translate `
  -F "file=@input.eng.srt" `
  -F "source=eng_Latn" `
  -F "target=nob_Latn" `
  -F "engine=nllb" `
  -F "progress_key=$uuid" `
  -o out.nob.srt -D headers.txt

# (optional) live progress
curl -N "http://localhost:8080/translate_sse?key=$uuid"
```

### Batch a folder (PowerShell)

```powershell
$src = "eng_Latn"; $tgt = "nob_Latn"
Get-ChildItem -Path . -Filter *.srt | ForEach-Object {
  $uuid = [guid]::NewGuid().ToString()
  $in = $_.FullName
  $out = ($_.BaseName -replace '\.[a-z]{2,3}$','') + ".nob.srt"
  curl http://localhost:8080/translate `
    -F "file=@$in" -F "source=$src" -F "target=$tgt" -F "engine=nllb" -F "progress_key=$uuid" `
    -o $out | Out-Null
}
```

---

## 4) Engine selection

- `nllb` — Use Meta’s NLLB‑200 (via the internal service). Highest quality; GPU‑accelerated if enabled.
- `libre` — Use LibreTranslate (Argos) fallback directly.
- `auto` — Try NLLB first, then fallback to LibreTranslate if NLLB fails.
- `argos` — **Pass‑through stub** (returns the original text unchanged). Useful for testing pipeline behavior.

---

## 5) Common pitfalls

- **Unsupported language code:** Server returns `400`. Use a valid FLORES-200 code or a known alias (`en`, `nb`, `es`, …).  
- **SSE without key:** `GET /translate_sse` requires `?key=`; otherwise you’ll get `400`.
- **Weird line breaks:** The server merges multi‑line cues for better translation and then splits back, preserving timing and formatting; if you still see odd wraps, open an issue with a sample SRT.

---

### Reference: typical aliases → FLORES

- `en` → `eng_Latn`  
- `nb`, `no`, `nob` → `nob_Latn`  
- `nn` → `nno_Latn`  
- `sv` → `swe_Latn`, `da` → `dan_Latn`, `de` → `deu_Latn`, `fr` → `fra_Latn`, `es` → `spa_Latn`, …
---



## Configuration (.env)

Key variables (see `.env` for the authoritative list):

| Variable | Example | Meaning |
|---|---|---|
| `MODEL` | `facebook/nllb-200-3.3B` | Hugging Face model id to pull |
| `MODEL_DIR` | `C:\models\nllb-200-3.3B` | Local model path (enables offline load) |
| `BATCH_SIZE` | `8` | Translation batch size |


> Change `MODEL` or `MODEL_DIR` then restart via `setup.ps1` option 2 (GPU) or 3 (CPU) to rebuild.

---

## GPU vs CPU

Two compose files:

- `docker-compose.gpu.yml` — enables `gpus: all` and CUDA env.
- `docker-compose.yml` — CPU‑only baseline.

If a full rebuild is needed (e.g., to clear a stale image), the GPU variant is:

```powershell
docker compose -f docker-compose.gpu.yml build app && `
docker compose -f docker-compose.gpu.yml up -d app
```
For CPU only use 
```powershell
docker compose -f docker-compose.yml build app && `
docker compose -f docker-compose.yml up -d app
```
`setup.ps1` normally handles builds/starts; use the manual command when you explicitly want a clean rebuild.

---

## Language list & filenames

- The UI loads **FLORES‑200** codes from `app/static/flores200.json`.
- Output filenames are normalized: e.g., `Show - S01E03.eng.srt` → `Show - S01E03.nb.srt`.
- Merged multiline entries are split back to match the original structure.

---

## Troubleshooting

- **No model loaded**: ensure `.env` points to a valid `MODEL` or `MODEL_DIR`. Re‑run `setup.ps1` and choose option 1 to download models, 2/3 for build or 4/5 to start.
- **GPU not used**: verify NVIDIA drivers + Container Toolkit (Linux) or WSL2 GPU (Windows). Run `./health.ps1` and check `device`/`cuda_available` fields.
- **Stale images/config**: do a clean rebuild (see **GPU vs CPU**), or `docker compose down -v` then rebuild.

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

- The **app** speaks to **nllb** via JSON batches. Forced BOS is set from the selected FLORES target code.
- `/healthz` in **nllb** returns configured vs. actually loaded model, plus device details.
- After each batch, the GPU path performs **VRAM cleanup** to reduce fragmentation.
---

Happy translating. The world is large; your subtitles should be too.
