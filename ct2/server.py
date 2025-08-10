import os
import unicodedata
import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import ctranslate2 as ct
from transformers import AutoTokenizer

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ct2-server")

# ---- Config via env ----
MODEL_DIR = os.getenv("CT2_MODEL_DIR", "/models/en-nor-ct2")
DEVICE = os.getenv("CT2_DEVICE", "cpu")                 # "cpu" | "cuda"
COMPUTE_TYPE = os.getenv("CT2_COMPUTE_TYPE", "default") # e.g. "int8", "int8_float16"
BEAM_SIZE = int(os.getenv("CT2_BEAM_SIZE", "1"))        # greedy = fastest
MAX_BATCH_TOKENS = int(os.getenv("CT2_MAX_BATCH_TOKENS", "4096"))
INTRA_THREADS = int(os.getenv("CT2_INTRA_THREADS", "0"))
INTER_THREADS = int(os.getenv("CT2_INTER_THREADS", "1"))
NO_REPEAT_NGRAM = int(os.getenv("CT2_NO_REPEAT_NGRAM", "3"))
REPETITION_PENALTY = float(os.getenv("CT2_REPETITION_PENALTY", "1.1"))
TOKENIZER_SRC = os.getenv("CT2_TOKENIZER_SRC", "jkorsvik/opus-mt-eng-nor")

app = FastAPI(title="CT2 Marian Translator (en→nb/nn)")

class TranslateIn(BaseModel):
    q: List[str]
    source: Optional[str] = None
    target: Optional[str] = "nb"

class TranslateOut(BaseModel):
    translatedText: List[str]

def _tgt_tok(tgt: Optional[str]) -> str:
    if not tgt:
        return ">>nob<<"
    t = tgt.lower()
    if t in ("nb", "no", "nob"):
        return ">>nob<<"
    if t in ("nn", "nno", "nynorsk"):
        return ">>nno<<"
    return ">>nob<<"

# ---- Load model + tokenizer ----
try:
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_SRC)
    EOS = tokenizer.eos_token or "</s>"

    translator = ct.Translator(
        MODEL_DIR,
        device=DEVICE,
        inter_threads=INTER_THREADS,
        intra_threads=INTRA_THREADS,
        compute_type=COMPUTE_TYPE,
    )
    log.info("CT2 server initialized: model=%s device=%s compute_type=%s", MODEL_DIR, DEVICE, COMPUTE_TYPE)
except Exception as e:
    log.exception("Failed to initialize")
    raise RuntimeError(f"Failed to initialize CT2 server: {e}")

@app.get("/healthz")
def health():
    return {
        "ok": True,
        "model_dir": MODEL_DIR,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "beam_size": BEAM_SIZE,
        "max_batch_tokens": MAX_BATCH_TOKENS,
        "intra_threads": INTRA_THREADS,
        "inter_threads": INTER_THREADS,
        "no_repeat_ngram": NO_REPEAT_NGRAM,
        "repetition_penalty": REPETITION_PENALTY,
        "tokenizer_src": TOKENIZER_SRC,
        "default_target": "nb",
    }

@app.post("/translate", response_model=TranslateOut)
def translate(payload: TranslateIn):
    try:
        texts = payload.q
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise HTTPException(status_code=400, detail="q must be a list of strings")

        tgt_token = _tgt_tok(payload.target)

        # 1) Source: prepend target language token on the SOURCE text (OPUS-MT convention)
        #    Use encode(add_special_tokens=True) to get the exact ids (incl. </s>) expected by the model,
        #    then convert ids → tokens (what CT2 expects).
        src_tokens_batch: List[List[str]] = []
        for s in texts:
            prefixed = f"{tgt_token} {s}"
            ids = tokenizer.encode(prefixed, add_special_tokens=True)
            toks = tokenizer.convert_ids_to_tokens(ids)
            if not toks:
                toks = [tgt_token]
            src_tokens_batch.append(toks)

        # 2) Target prefix: enforce the target language token AS TARGET PREFIX as well.
        #    This stabilizes multilingual Marian decoding in CT2.
        tgt_prefix_batch: List[List[str]] = [[tgt_token] for _ in texts]

        results = translator.translate_batch(
            src_tokens_batch,
            target_prefix=tgt_prefix_batch,
            beam_size=BEAM_SIZE,
            batch_type="tokens",
            max_batch_size=MAX_BATCH_TOKENS,
            no_repeat_ngram_size=NO_REPEAT_NGRAM,
            repetition_penalty=REPETITION_PENALTY,
            end_token=EOS,
            return_end_token=False,
            return_scores=False,
            replace_unknowns=False,
        )

        outs: List[str] = []
        for r in results:
            out_tokens = r.hypotheses[0] if r.hypotheses else []
            # Convert tokens → ids → decode (skip_special_tokens=True) for safest detok
            out_ids = tokenizer.convert_tokens_to_ids(out_tokens) if out_tokens else []
            text = tokenizer.decode(out_ids, skip_special_tokens=True)
            outs.append(unicodedata.normalize("NFC", text))

        return TranslateOut(translatedText=outs)

    except HTTPException:
        raise
    except Exception as e:
        log.exception("Translate request failed")
        return JSONResponse(status_code=500, content={"error": str(e)})
