# srtxlate.py — SRT helpers + engines (NLLB + Libre fallback) with cue-aware batching
import re
import unicodedata
from typing import List, Tuple, Dict, Callable, Optional
import requests

# -----------------------------
# Unicode helpers
# -----------------------------
def _nfc(s: str) -> str:
    """Normalize string to NFC form."""
    return unicodedata.normalize("NFC", s or "")

def _strip_bom(line: str) -> str:
    # Handle BOM on very first line (can break the index parse)
    return line.lstrip("\ufeff") if line else line

# -----------------------------
# Tag protection (keep HTML-ish tags intact during translation)
# -----------------------------
_TAG_RE = re.compile(r"<[^>]+>")

def _protect_tags(text: str) -> Tuple[str, Dict[str, str]]:
    """Replace tags with placeholders to protect them from translation."""
    tags: Dict[str, str] = {}

    def _replace(m):
        key = f"__TAG{len(tags)}__"
        tags[key] = m.group(0)
        return key

    protected_text = _TAG_RE.sub(_replace, text)
    return protected_text, tags

def _restore_tags(text: str, tags: Dict[str, str]) -> str:
    """Restore placeholders back to original tags."""
    for key, val in tags.items():
        text = text.replace(key, val)
    return text

# -----------------------------
# SRT split/join
# -----------------------------
_TIME_RE = re.compile(r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")

def _is_index_line(line: str) -> bool:
    return line.strip().isdigit()

def _is_time_line(line: str) -> bool:
    return bool(_TIME_RE.search(line or ""))

def _split_srt(s: str) -> List[List[str]]:
    """
    Split SRT file content into a list of blocks (each block is a list of lines).
    Keeps indices/timestamps untouched. Handles BOM on the first line.
    """
    if not s:
        return []
    normalized = s.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n{2,}", normalized)
    blocks: List[List[str]] = []
    for chunk in chunks:
        if not chunk.strip():
            continue
        lines = chunk.split("\n")
        # Strip BOM on the very first physical line of the file
        if not blocks and lines:
            lines[0] = _strip_bom(lines[0])
        blocks.append(lines)
    return blocks

def _join_srt(blocks: List[List[str]]) -> str:
    """Join blocks of lines back into a single SRT string, with trailing newline."""
    return "\n\n".join("\n".join(block) for block in blocks) + "\n"

# -----------------------------
# Language normalization and filename suffix mapping
# -----------------------------
_alias_to_flores = {
    "en": "eng_Latn", "eng": "eng_Latn",
    "nb": "nob_Latn", "no": "nob_Latn", "nob": "nob_Latn",
    "nn": "nno_Latn",
    "sv": "swe_Latn", "da": "dan_Latn", "fi": "fin_Latn",
    "de": "deu_Latn", "fr": "fra_Latn", "es": "spa_Latn",
    "it": "ita_Latn", "pt": "por_Latn", "nl": "nld_Latn",
    "pl": "pol_Latn", "ru": "rus_Cyrl", "uk": "ukr_Cyrl",
    "zh": "zho_Hans", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "tr": "tur_Latn", "ar": "arb_Arab",
    "cs": "ces_Latn", "hu": "hun_Latn", "ro": "ron_Latn",
    "el": "ell_Grek", "he": "heb_Hebr", "id": "ind_Latn",
    "vi": "vie_Latn", "th": "tha_Thai", "hi": "hin_Deva",
    "bn": "ben_Beng", "ur": "urd_Arab", "ta": "tam_Taml",
    "fa": "pes_Arab", "sr": "srp_Cyrl", "hr": "hrv_Latn",
}

def normalize_lang_code(code: str) -> str:
    """
    Normalize input language code or alias to a FLORES-200 code.
    If code contains '_', assume it's already a FLORES code.
    """
    code = (code or "").strip()
    if "_" in code:
        return code
    return _alias_to_flores.get(code.lower(), code)

# Short code for filenames (prefer ISO-639-1 where obvious)
def target_suffix_for_filename(flores_code: str) -> str:
    inv = {v: k for k, v in _alias_to_flores.items()}
    return inv.get(flores_code, flores_code.split("_", 1)[0][:3].lower())

# -----------------------------
# Heuristics for ALL-CAPS sound/stage lines
# -----------------------------
# quick “no lowercase” test; tolerant to punctuation/diacritics
_ALLCAPS_RE = re.compile(r"^[^a-zåäöæøéèáíóúñçß]+$")

def _is_allcaps_marker(line: str) -> bool:
    """
    Treat short ALL-CAPS cues like [DOOR OPENS], (MUSIC), SIRENS as 'marker-ish'.
    We do not merge these with neighboring lines so they don't split a sentence.
    """
    txt = _TAG_RE.sub("", line or "").strip()
    if len(txt) == 0:
        return False
    if len(txt) <= 40 and _ALLCAPS_RE.match(txt) and any(ch.isalpha() for ch in txt):
        return True
    return False

# -----------------------------
# Reflow helpers (avoid mid-word splits)
# -----------------------------
def _split_to_n_lines_preserving_words(text: str, n: int, target_lengths: Optional[List[int]] = None) -> List[str]:
    """
    Split 'text' into exactly n lines, preferring spaces near proportional cut points.
    If target_lengths provided, it guides the approximate lengths per line (based on original lines).
    Falls back to a last-resort balanced split if no spaces are available.
    """
    text = " ".join((text or "").replace("\n", " ").split())  # collapse whitespace
    if n <= 1:
        return [text]

    # If we can split exactly by newlines already, do it
    parts = [p.strip() for p in re.split(r"\r?\n", text) if p.strip()]
    if len(parts) == n:
        return parts

    total_len = max(1, len(text))
    if not target_lengths or len(target_lengths) != n:
        # proportional targets
        target_lengths = [round(total_len / n)] * n

    out: List[str] = []
    start = 0
    for i in range(n):
        remaining = text[start:].lstrip()
        # last piece = rest
        if i == n - 1:
            out.append(remaining)
            break

        # target cut (approx)
        cut_target = min(len(remaining), max(1, target_lengths[i]))
        # find nearest space around cut_target (prefer right)
        best = None
        # search right
        r = remaining.find(" ", cut_target)
        if r != -1:
            best = r
        # if not found right, search left
        if best is None:
            l = remaining.rfind(" ", 0, cut_target)
            if l != -1:
                best = l
        # if still none, no spaces — do hard cut but avoid breaking multi-byte chars
        if best is None:
            best = cut_target

        left = remaining[:best].rstrip()
        out.append(left)
        # move start past the space (if we cut on a space)
        start += len(remaining[:best])
        # skip one space at boundary if present
        if start < len(text) and text[start] == " ":
            start += 1

    # pad empties if something went wrong
    while len(out) < n:
        out.append("")
    return out[:n]

# -----------------------------
# NLLB service call (batched)
# -----------------------------
def _nllb_translate_batched(
    lines: List[str],
    source: str,
    target: str,
    nllb_endpoint: str,
    batch_size: int,
    glossary: Dict[str, str],
    progress_cb: Optional[Callable[[int, int], None]],
) -> List[str]:
    if not lines:
        return []

    # Protect tags + simple glossary substitutions before sending
    protected_pairs = []
    prepped: List[str] = []
    for ln in lines:
        ln0, tags = _protect_tags(ln)
        # tiny glossary (lowercase match)
        gtext = ln0
        for k, v in glossary.items():
            gtext = re.sub(rf"\b{re.escape(k)}\b", v, gtext, flags=re.IGNORECASE)
        protected_pairs.append(tags)
        prepped.append(gtext)

    out_texts: List[str] = []
    total = len(prepped)
    done = 0
    if progress_cb:
        progress_cb(total, done)

    for i in range(0, total, max(1, batch_size)):
        batch = prepped[i : i + batch_size]
        payload = {
            "q": batch,
            "source": source,
            "target": target,
            "batch_size": batch_size,
        }
        r = requests.post(f"{nllb_endpoint.rstrip('/')}/translate", json=payload, timeout=600)
        r.raise_for_status()
        data = r.json()
        out = data.get("translatedText", [])
        out_texts.extend(out)
        done = min(total, done + len(batch))
        if progress_cb:
            progress_cb(total, done)

    # Restore protected tags and normalize
    restored_lines: List[str] = []
    for text, tags in zip(out_texts, protected_pairs):
        restored = _restore_tags(text, tags)
        restored_lines.append(_nfc(restored))
    return restored_lines

# -----------------------------
# LibreTranslate fallback (Argos)
# -----------------------------
def _lt_translate_batched(
    lines: List[str],
    source: str,
    target: str,
    libre_endpoint: str,
    api_key: str,
    batch_size: int,
    progress_cb: Optional[Callable[[int, int], None]]
) -> List[str]:
    if not lines:
        return []
    # Use first two letters (ISO-639-1) for LibreTranslate if possible
    src = (source or "en")[:2]
    tgt = (target or "nb")[:2]
    out_lines: List[str] = []
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
            out_lines.extend([item.get("translatedText", "") for item in res])
        else:
            out_lines.extend(res.get("translatedText", []))

        done_lines = min(total_lines, done_lines + len(batch))
        if progress_cb:
            progress_cb(total_lines, done_lines)

    return out_lines

# -----------------------------
# Argos Translate fallback (last resort no-op)
# -----------------------------
def _argos_translate(
    lines: List[str],
    source: str,
    target: str,
    progress_cb: Optional[Callable[[int, int], None]]
) -> List[str]:
    if progress_cb:
        progress_cb(len(lines), len(lines))
    return lines

# =============================
# Translation driver
# =============================
_SENTINEL = "__NL__"  # unlikely to be translated; we split on this after translation

def translate_srt_with_progress(
    srt_text: str,
    source: str,
    target: str,
    engine: str = "auto",
    nllb_endpoint: str = "http://nllb:6100",
    libre_endpoint: str = "http://libretranslate:5000",
    libre_api_key: str = "",
    progress_cb: Optional[Callable[[int, int], None]] = None,
    batch_size: int = 64
) -> str:
    # Split into blocks
    blocks = _split_srt(srt_text)

    # Build groups to translate (only from text lines)
    groups: List[str] = []  # what we send to the engine
    placements: List[Tuple[int, List[int]]] = []  # (block_index, [line_indexes_within_block])

    for bi, block in enumerate(blocks):
        # ensure BOM removed on first line
        if bi == 0 and block:
            block[0] = _strip_bom(block[0])

        # Identify the *text* lines in the cue
        text_idxs = [li for li, line in enumerate(block)
                     if not _is_index_line(line) and not _is_time_line(line) and (line is not None)]
        # Keep empty text lines as is — nothing to translate
        text_idxs = [li for li in text_idxs if block[li].strip() != ""]

        if not text_idxs:
            continue

        # Partition text lines into runs: marker lines stand alone; others are merged
        run: List[int] = []
        for li in text_idxs:
            line = block[li]
            if _is_allcaps_marker(line):
                if run:
                    merged = f" {_SENTINEL} ".join(block[k] for k in run)
                    groups.append(merged)
                    placements.append((bi, run[:]))
                    run.clear()
                groups.append(line)          # marker stands alone
                placements.append((bi, [li]))
            else:
                run.append(li)

        if run:
            merged = f" {_SENTINEL} ".join(block[k] for k in run)
            groups.append(merged)
            placements.append((bi, run[:]))

    # Nothing to translate?
    if not groups:
        return _join_srt(blocks)

    use_engine = (engine or "auto").lower()
    translated: List[str] = []

    # very small example glossary; adjust/remove as you like
    glossary = {
        "removal men": "movers",
        "removals men": "movers",
    }

    # Try NLLB first (or only)
    if use_engine in ("nllb", "auto"):
        try:
            translated = _nllb_translate_batched(
                groups, normalize_lang_code(source), normalize_lang_code(target),
                nllb_endpoint, batch_size=batch_size,
                glossary=glossary, progress_cb=progress_cb
            )
        except Exception:
            if use_engine == "nllb":
                raise
            translated = []

    # Fallback to LibreTranslate
    if not translated and use_engine in ("libre", "auto"):
        try:
            translated = _lt_translate_batched(
                groups, source, target, libre_endpoint, libre_api_key,
                batch_size=batch_size, progress_cb=progress_cb
            )
        except Exception:
            if use_engine == "libre":
                raise
            translated = []

    # Last resort
    if not translated:
        translated = _argos_translate(groups, source, target, progress_cb=progress_cb)

    # Place translated strings back into the original blocks
    gi = 0
    for (bi, idxs) in placements:
        text = _nfc(translated[gi] if gi < len(translated) else "")
        gi += 1

        # Single line: straight replace
        if len(idxs) == 1:
            blocks[bi][idxs[0]] = text.strip()
            continue

        # Multi-line run: try to split by sentinel first
        parts = [p.strip() for p in text.split(_SENTINEL)]
        if len(parts) != len(idxs):
            # If the model returned embedded newlines that match line count, accept them
            nl_parts = [p.strip() for p in re.split(r"\r?\n", text) if p.strip()]
            if len(nl_parts) == len(idxs):
                parts = nl_parts
            else:
                # Use reflow that avoids splitting words; guide by original line lengths
                orig_lens = [len(blocks[bi][k]) for k in idxs]
                parts = _split_to_n_lines_preserving_words(text, len(idxs), target_lengths=orig_lens)

        # Assign back
        for li, part in zip(idxs, parts):
            blocks[bi][li] = part

    # Final cleanup: ensure every block still has index + timestamp intact
    # (do not create or renumber indices; we never touched those lines)
    return _join_srt(blocks)
