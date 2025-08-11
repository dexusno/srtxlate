import os
import unicodedata
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

MODEL_NAME = os.getenv("NLLB_MODEL", "facebook/nllb-200-distilled-600M")
DEVICE = "cpu" if os.getenv("NLLB_DEVICE", "cpu") == "cpu" or not torch.cuda.is_available() else "cuda"
BATCH_SIZE = int(os.getenv("NLLB_BATCH_SIZE", "32"))
MAX_NEW_TOKENS = int(os.getenv("NLLB_MAX_NEW_TOKENS", "256"))
NUM_BEAMS = int(os.getenv("NLLB_NUM_BEAMS", "1"))

# Lazy globals
_tokenizer = None
_model = None

def get_model():
    global _tokenizer, _model
    if _model is None or _tokenizer is None:
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
        _model.to(DEVICE)
        _model.eval()
    return _tokenizer, _model

def normalize_text(s: str) -> str:
    # Keep Norwegian diacritics stable
    return unicodedata.normalize("NFC", s)

class TranslateIn(BaseModel):
    q: List[str]
    source: str = "eng_Latn"
    target: str = "nob_Latn"
    max_new_tokens: Optional[int] = None
    num_beams: Optional[int] = None

class TranslateOut(BaseModel):
    translatedText: List[str]

app = FastAPI(title="NLLB Translation Server", version="1.0.0")

@app.get("/healthz")
def healthz():
    return {"ok": True, "model": MODEL_NAME, "device": DEVICE}

@app.post("/translate", response_model=TranslateOut)
@torch.no_grad()
def translate(body: TranslateIn):
    tokenizer, model = get_model()

    # Use tokenizer to get target language id; fall back via convert_tokens_to_ids if needed.
    # Some Transformers versions expose `lang_code_to_id`, others require `convert_tokens_to_ids`.
    try:
        forced_bos = tokenizer.lang_code_to_id[body.target]
    except Exception:
        forced_bos = tokenizer.convert_tokens_to_ids(body.target)

    max_new = body.max_new_tokens or MAX_NEW_TOKENS
    beams = body.num_beams or NUM_BEAMS

    out_texts: List[str] = []
    # Simple batching by count
    q = [normalize_text(x) for x in body.q]
    for i in range(0, len(q), BATCH_SIZE):
        batch = q[i:i+BATCH_SIZE]
        inputs = tokenizer(batch, return_tensors="pt", padding=True, truncation=True).to(DEVICE)
        outputs = model.generate(**inputs,
                                 forced_bos_token_id=forced_bos,
                                 max_new_tokens=max_new,
                                 num_beams=beams)
        decoded = tokenizer.batch_decode(outputs, skip_special_tokens=True)
        decoded = [normalize_text(s) for s in decoded]
        out_texts.extend(decoded)

    return TranslateOut(translatedText=out_texts)
