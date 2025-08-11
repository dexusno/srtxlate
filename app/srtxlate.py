import re
import unicodedata
from typing import List, Tuple, Dict, Callable, Optional
import requests

# --- Tag protection (keep HTML-like tags intact) ---
_TAG_RE = re.compile(r"<[^>]+>")

def _protect_tags(text: str):
    tags = {}
    def repl(m):
        key = f"__TAG{len(tags)}__"
        tags[key] = m.group(0)
        return key
    return _TAG_RE.sub(repl, text), tags

def _restore_tags(text: str, tags: Dict[str, str]) -> str:
    for k, v in tags.items():
        text = text.replace(k, v)
    return text

def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)

# --- SRT helpers ---
_TIME_RE = re.compile(r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")

def _split_srt(s: str) -> List[List[str]]:
    chunks = re.split(r"\n{2,}|\r\n\r\n", s.replace("\r\n", "\n"))
    return [c.split("\n") for c in chunks if c.strip()]

def _join_srt(blocks: List[List[str]]) -> str:
    return "\n\n".join("\n".join(b) for b in blocks) + "\n"

def _is_index_line(line: str) -> bool:
    return line.strip().isdigit()

def _is_time_line(line: str) -> bool:
    return bool(_TIME_RE.search(line))

# --- Language normalization & filename suffix mapping ---
# Pass-through for valid FLORES codes (code contains "_").
# Minimal aliases for common ISO-639-1 inputs.
_ALIAS_TO_FLORES = {
    "en": "eng_Latn",
    "eng": "eng_Latn",
    "nb": "nob_Latn",
    "no": "nob_Latn",
    "nob": "nob_Latn",
    "nn": "nno_Latn",
    "sv": "swe_Latn",
    "da": "dan_Latn",
    "fi": "fin_Latn",
    "de": "deu_Latn",
    "fr": "fra_Latn",
    "es": "spa_Latn",
    "it": "ita_Latn",
    "pt": "por_Latn",
    "nl": "nld_Latn",
    "pl": "pol_Latn",
    "ru": "rus_Cyrl",
    "uk": "ukr_Cyrl",
    "zh": "zho_Hans",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "tr": "tur_Latn",
    "ar": "arb_Arab",
}

def normalize_lang_code(code: str) -> str:
    """
    Normalize to FLORES-200 code used by NLLB.
    If input already looks like FLORES (has "_"), return as-is.
    Else map a few common ISO-style aliases; otherwise return input unchanged.
    """
    if not code:
        return "eng_Latn"
    c = code.strip()
    if "_" in c:
        return c
    lc = c.lower()
    return _ALIAS_TO_FLORES.get(lc, c)

# Preferred filename suffixes (ISO-639-1 where widely used; else fallback).
# For codes not in this table, we fall back to the 3-letter part before the underscore.
_FLORES_TO_SHORT: Dict[str, str] = {
    "eng_Latn": "en",
    "nob_Latn": "nb",
    "nno_Latn": "nn",
    "swe_Latn": "sv",
    "dan_Latn": "da",
    "fin_Latn": "fi",
    "isl_Latn": "is",
    "fao_Latn": "fo",
    "deu_Latn": "de",
    "fra_Latn": "fr",
    "spa_Latn": "es",
    "ita_Latn": "it",
    "por_Latn": "pt",
    "nld_Latn": "nl",
    "pol_Latn": "pl",
    "ces_Latn": "cs",
    "slk_Latn": "sk",
    "hun_Latn": "hu",
    "ron_Latn": "ro",
    "ell_Grek": "el",
    "rus_Cyrl": "ru",
    "ukr_Cyrl": "uk",
    "bul_Cyrl": "bg",
    "srp_Cyrl": "sr",
    "srp_Latn": "sr",
    "hrv_Latn": "hr",
    "bos_Latn": "bs",
    "slv_Latn": "sl",
    "sqi_Latn": "sq",
    "tur_Latn": "tr",
    "arb_Arab": "ar",
    "heb_Hebr": "he",
    "pes_Arab": "fa",
    "kmr_Latn": "ku",
    "hin_Deva": "hi",
    "ben_Beng": "bn",
    "urd_Arab": "ur",
    "tam_Taml": "ta",
    "tel_Telu": "te",
    "mal_Mlym": "ml",
    "sin_Sinh": "si",
    "zho_Hans": "zh",
    "zho_Hant": "zh",
    "jpn_Jpan": "ja",
    "kor_Hang": "ko",
    "vie_Latn": "vi",
    "tha_Thai": "th",
    "ind_Latn": "id",
    "zsm_Latn": "ms",
    "tgl_Latn": "tl",
    "swh_Latn": "sw",
    "afr_Latn": "af",
    "amh_Ethi": "am",
}

def target_suffix_for_filename(target_code: str) -> str:
    """
    Produce a short language suffix for filenames:
      - Use a preferred ISO-639-1 code when known (from table above).
      - Else fall back to the 3-letter part before the underscore (FLORES code).
      - Else 'xx'.
    """
    c = normalize_lang_code(target_code)
    if c in _FLORES_TO_SHORT:
        return _FLORES_TO_SHORT[c]
    if "_" in c and len(c) >= 3:
        return c.split("_", 1)[0]
    return "xx"

# --- NLLB batched translate with progress callback ---
def _nllb_translate_batched(
    lines: List[str],
    source: str,
    target: str,
    nllb_endpoint: str,
    batch_size: int,
    glossary: Optional[Dict[str, str]],
    progress_cb: Optional[Callable[[int, int], None]],
) -> List[str]:
    if not lines:
        return []

    src = normalize_lang_code(source)
    tgt = normalize_lang_code(target)

    # Protect tags first to avoid being mangled by MT
    payload_lines: List[str] = []
    tag_maps: List[Dict[str, str]] = []
    for line in lines:
        t, tags = _protect_tags(line)
        payload_lines.append(_nfc(t))
        tag_maps.append(tags)

    out_texts: List[str] = []
    total_lines = len(payload_lines)
    done_lines = 0

    # First progress ping (0/N)
    if progress_cb:
        progress_cb(total_lines, done_lines)

    for i in range(0, total_lines, max(1, batch_size)):
        batch = payload_lines[i : i + batch_size]
        body = {"q": batch, "source": src, "target": tgt}
        if glossary:
            body["glossary"] = glossary

        r = requests.post(f"{nllb_endpoint.rstrip('/')}/translate", json=body, timeout=600)
        r.raise_for_status()
        outs = r.json().get("translatedText", [])
        out_texts.extend(outs)

        done_lines = min(total_lines, done_lines + len(batch))
        if progress_cb:
            progress_cb(total_lines, done_lines)

    # Restore tags and normalize
    restored: List[str] = []
    for text, tags in zip(out_texts, tag_maps):
        restored.append(_nfc(_restore_tags(text, tags)))
    return restored

# --- LibreTranslate fallback (optional) ---
def _lt_translate_batched(
    lines: List[str],
    source: str,
    target: str,
    libre_endpoint: str,
    api_key: str,
    batch_size: int,
    progress_cb: Optional[Callable[[int, int], None]],
) -> List[str]:
    if not lines:
        return []
    src = (source or "en")[:2]
    tgt = (target or "nb")[:2]
    out: List[str] = []
    total_lines = len(lines)
    done_lines = 0

    if progress_cb:
        progress_cb(total_lines, done_lines)

    for i in range(0, total_lines, max(1, batch_size)):
        batch = lines[i : i + batch_size]
        payload = {"q": batch, "source": src, "target": tgt, "format": "text"}
        if api_key:
            payload["api_key"] = api_key
        r = requests.post(f"{libre_endpoint.rstrip('/')}/translate", json=payload, timeout=600)
        r.raise_for_status()
        res = r.json()
        if isinstance(res, list):
            out.extend([it.get("translatedText", "") for it in res])
        else:
            out.extend(res.get("translatedText", []))

        done_lines = min(total_lines, done_lines + len(batch))
        if progress_cb:
            progress_cb(total_lines, done_lines)

    return out

# --- Argos no-op (compatibility only) ---
def _argos_translate(lines: List[str], source: str, target: str,
                     progress_cb: Optional[Callable[[int, int], None]]) -> List[str]:
    if progress_cb:
        progress_cb(len(lines), len(lines))
    return lines

def translate_srt_with_progress(
    srt_text: str,
    source: str,
    target: str,
    engine: str = "auto",
    nllb_endpoint: str = "http://nllb:6100",
    libre_endpoint: str = "http://libretranslate:5000",
    libre_api_key: str = "",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    batch_size: int = 64,
) -> str:
    # Parse SRT -> blocks
    blocks = _split_srt(srt_text)

    # Collect text lines to translate, keep their positions
    text_positions: List[Tuple[int, int]] = []
    payload: List[str] = []
    for bi, block in enumerate(blocks):
        for li, line in enumerate(block):
            if _is_index_line(line) or _is_time_line(line) or not line.strip():
                continue
            text_positions.append((bi, li))
            payload.append(line)

    use_engine = (engine or "auto").lower()
    translated: List[str] = []

    # Example glossary for known pain points; extend/disable as needed
    glossary = {
        "removal men": "movers",
        "removals men": "movers",
    }

    if use_engine in ("nllb", "auto"):
        try:
            translated = _nllb_translate_batched(
                payload, source, target, nllb_endpoint,
                batch_size=batch_size, glossary=glossary, progress_cb=progress_cb
            )
        except Exception:
            if use_engine == "nllb":
                raise
            translated = []

    if not translated and use_engine in ("libre", "auto"):
        try:
            translated = _lt_translate_batched(
                payload, source, target, libre_endpoint, libre_api_key,
                batch_size=batch_size, progress_cb=progress_cb
            )
        except Exception:
            if use_engine == "libre":
                raise
            translated = []

    if not translated:
        translated = _argos_translate(payload, source, target, progress_cb=progress_cb)

    # Reinsert translated lines back into blocks
    it = iter(translated)
    for (bi, li) in text_positions:
        blocks[bi][li] = next(it, "")

    return _join_srt(blocks)
