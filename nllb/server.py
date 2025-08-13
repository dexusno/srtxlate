import os
import gc
import unicodedata
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# --- Config via environment (.env) ---
MODEL_NAME = os.getenv("NLLB_MODEL", "facebook/nllb-200-distilled-600M")
MODEL_DIR  = os.getenv("NLLB_MODEL_DIR", "").strip()

# Prefer CUDA if available; allow override with NLLB_DEVICE=cpu|cuda
_env_dev = os.getenv("NLLB_DEVICE", "").lower()
if _env_dev == "cuda" and torch.cuda.is_available():
    DEVICE = "cuda"
elif _env_dev == "cpu":
    DEVICE = "cpu"
else:
    DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

BATCH_SIZE      = int(os.getenv("NLLB_BATCH_SIZE", "32"))
MAX_NEW_TOKENS  = int(os.getenv("NLLB_MAX_NEW_TOKENS", "256"))
NUM_BEAMS       = int(os.getenv("NLLB_NUM_BEAMS", "1"))

# Sound-effect / stage-direction handling:
#   translate_upper (default): translate all-caps/[]/() cues, then re-UPPERCASE and re-wrap
#   passthrough: leave such cues unmodified
SFX_POLICY = os.getenv("NLLB_SFX_POLICY", "translate_upper")

# --- Lazy-loaded globals ---
_tokenizer: Optional[AutoTokenizer] = None
_model: Optional[AutoModelForSeq2SeqLM] = None
_loaded_model_name: Optional[str] = None  # path or hub id actually loaded

def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")

def _path_has_model(path: str) -> bool:
    if not path:
        return False
    try:
        return os.path.isfile(os.path.join(path, "config.json"))
    except Exception:
        return False

def get_model() -> Tuple[AutoTokenizer, AutoModelForSeq2SeqLM]:
    """Lazy-load tokenizer + model from local dir if present, else from hub."""
    global _tokenizer, _model, _loaded_model_name

    if _model is not None and _tokenizer is not None:
        return _tokenizer, _model

    use_local = _path_has_model(MODEL_DIR)
    src = MODEL_DIR if use_local else MODEL_NAME
    local_only = bool(use_local)

    tok = AutoTokenizer.from_pretrained(src, use_fast=True, local_files_only=local_only)
    mdl = AutoModelForSeq2SeqLM.from_pretrained(src, local_files_only=local_only)

    mdl.eval()
    if DEVICE == "cuda":
        mdl.to("cuda")

    _tokenizer, _model = tok, mdl
    _loaded_model_name = getattr(mdl, "name_or_path", src)
    return _tokenizer, _model

class TranslateIn(BaseModel):
    q: List[str]
    source: str
    target: str
    max_new_tokens: Optional[int] = None
    num_beams: Optional[int] = None
    batch_size: Optional[int] = None

class TranslateOut(BaseModel):
    translatedText: List[str]

app = FastAPI(title="NLLB Translation Server", version="1.1")

def _is_upper_cue(text: str) -> bool:
    # Heuristic: predominantly uppercase letters OR surrounded by []/()
    t = text.strip()
    if not t:
        return False
    if (t.startswith('[') and t.endswith(']')) or (t.startswith('(') and t.endswith(')')):
        inner = t[1:-1].strip()
    else:
        inner = t
    letters = [c for c in inner if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= 0.8

def _prep_for_model(text: str) -> Tuple[str, dict]:
    """
    Returns (possibly modified text, postprocess_info)
    postprocess_info keys:
      - 'upper': bool        -> upper-case the decoded result
      - 'wrap': tuple|None   -> (prefix, suffix) to re-attach e.g. [] or ()
    """
    t = text
    info = {'upper': False, 'wrap': None}
    s = t.strip()
    wrap = None
    if (s.startswith('[') and s.endswith(']')) or (s.startswith('(') and s.endswith(')')):
        wrap = (s[0], s[-1])
        core = s[1:-1].strip()
    else:
        core = s
    if SFX_POLICY == "passthrough":
        return t, info
    if _is_upper_cue(s):
        info['upper'] = True
        if wrap:
            info['wrap'] = wrap
        # Lowercase for translation, add a period to help the model treat it as a phrase
        core2 = core.lower()
        if core2 and core2[-1].isalnum():
            core2 = core2 + "."
        t = core2
    return t, info

def _post_from_model(decoded: str, info: dict) -> str:
    out = decoded.strip()
    # remove helper punctuation we might have added
    if out.endswith('.') or out.endswith('!'):
        out = out[:-1]
    if info.get('upper'):
        out = out.upper()
    wrap = info.get('wrap')
    if wrap:
        out = f"{wrap[0]}{out}{wrap[1]}"
    return out

@app.get("/healthz")
def healthz():
    return {
        "ok": True,
        "configured_model": MODEL_NAME,
        "configured_model_dir": MODEL_DIR or None,
        "loaded_model": _loaded_model_name or None,
        "device": DEVICE,
        "cuda_available": torch.cuda.is_available(),
        "sfx_policy": SFX_POLICY,
    }

@app.post("/translate", response_model=TranslateOut)
@torch.no_grad()
def translate(body: TranslateIn):
    tok, mdl = get_model()

    # forced BOS for target language (FLORES code like nob_Latn)
    try:
        forced_bos = tok.lang_code_to_id[body.target]
    except Exception:
        forced_bos = tok.convert_tokens_to_ids(body.target)
    if forced_bos is None:
        raise HTTPException(status_code=400, detail=f"Unsupported target language: {body.target}")

    max_new = int(body.max_new_tokens or MAX_NEW_TOKENS)
    beams   = int(body.num_beams or NUM_BEAMS)
    bs      = max(1, int(body.batch_size or BATCH_SIZE))

    lines = [nfc(x) for x in (body.q or [])]
    out: List[str] = []

    # Optionally set src_lang if the tokenizer supports it
    if hasattr(tok, "src_lang"):
        tok.src_lang = body.source

    i = 0
    while i < len(lines):
        chunk_lines = lines[i:i+bs]
        prepped = []
        infos = []
        for ln in chunk_lines:
            p, info = _prep_for_model(ln)
            prepped.append(p if p else "")
            infos.append(info)

        inputs = tok(prepped, return_tensors="pt", padding=True, truncation=True).to(DEVICE)

        if DEVICE == "cuda":
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                outputs = mdl.generate(
                    **inputs,
                    forced_bos_token_id=forced_bos,
                    max_new_tokens=max_new,
                    num_beams=beams,
                )
        else:
            outputs = mdl.generate(
                **inputs,
                forced_bos_token_id=forced_bos,
                max_new_tokens=max_new,
                num_beams=beams,
            )

        decoded = tok.batch_decode(outputs, skip_special_tokens=True)
        for dec, info in zip(decoded, infos):
            out.append(nfc(_post_from_model(dec, info)))

        del inputs, outputs
        if DEVICE == "cuda":
            torch.cuda.synchronize()
            torch.cuda.empty_cache()
        i += bs

    return TranslateOut(translatedText=out)

if __name__ == "__main__":
    import uvicorn
    print(f"[nllb] starting on {DEVICE} | configured_model={MODEL_NAME} | model_dir={MODEL_DIR or '-'} | sfx_policy={SFX_POLICY}")
    uvicorn.run("server:app", host="0.0.0.0", port=6100, reload=False, workers=1)
