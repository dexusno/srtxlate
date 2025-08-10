from __future__ import annotations
import re
from typing import List, Tuple, Dict, Optional
import srt
import requests
import argostranslate.package  # noqa: F401
import argostranslate.translate

TAG_PATTERN = re.compile(r"<[^>]+>")

def _protect_tags(text: str) -> Tuple[str, Dict[str, str]]:
    tags: Dict[str, str] = {}
    def repl(m):
        key = f"__TAG{len(tags)}__"
        tags[key] = m.group(0)
        return key
    return TAG_PATTERN.sub(repl, text), tags

def _restore_tags(text: str, tags: Dict[str, str]) -> str:
    for k, v in tags.items():
        text = text.replace(k, v)
    return text

def _split_keep_newlines(text: str) -> List[str]:
    return text.splitlines(keepends=False)

def _join_with_newlines(lines: List[str]) -> str:
    return "\n".join(lines)

# ---------- Argos local ----------
def _argos_translate_lines(lines: List[str], source: str, target: str) -> List[str]:
    out: List[str] = []
    for line in lines:
        if not line.strip():
            out.append(line); continue
        protected, tags = _protect_tags(line)
        translated = argostranslate.translate.translate(protected, source, target)
        out.append(_restore_tags(translated, tags))
    return out

# ---------- LibreTranslate remote (JSON then form fallback) ----------
def _parse_lt(res_json) -> List[str]:
    if isinstance(res_json, dict) and "error" in res_json:
        raise RuntimeError(f"LibreTranslate error: {res_json.get('error')}")
    if isinstance(res_json, dict):
        t = res_json.get("translatedText")
        if isinstance(t, str): return [t]
        if isinstance(t, list) and all(isinstance(x,str) for x in t): return t
        raise RuntimeError("Unexpected LT dict response")
    if isinstance(res_json, list):
        return [item["translatedText"] for item in res_json]
    raise RuntimeError("Unexpected LT response")

def _lt_post(endpoint: str, data_json: dict, data_form: List[Tuple[str,str]]) -> List[str]:
    r = requests.post(f"{endpoint.rstrip('/')}/translate", json=data_json, timeout=300)
    try:
        res = r.json()
    except Exception:
        r.raise_for_status()
        raise RuntimeError("LT non-JSON response")
    if not r.ok:
        text = ""
        try: text = r.text or ""
        except Exception: pass
        if r.status_code in (400,415) or "could not understand" in text.lower():
            r2 = requests.post(f"{endpoint.rstrip('/')}/translate", data=data_form, timeout=300)
            res2 = r2.json(); 
            if not r2.ok: raise RuntimeError(res2.get("error","LT error"))
            return _parse_lt(res2)
        if isinstance(res, dict) and "error" in res: raise RuntimeError(res["error"])
        r.raise_for_status()
    return _parse_lt(res)

def _lt_translate_lines(lines: List[str], source: str, target: str, endpoint: str, api_key: Optional[str]) -> List[str]:
    payload_q, tags_list, idx_map = [], [], []
    for i, line in enumerate(lines):
        if not line.strip(): continue
        protected, tags = _protect_tags(line)
        payload_q.append(protected); tags_list.append(tags); idx_map.append(i)
    if not payload_q: return lines
    j = {"q": payload_q, "source": source, "target": target, "format": "text"}
    if api_key: j["api_key"] = api_key
    f: List[Tuple[str,str]] = [("q", q) for q in payload_q] + [("source",source),("target",target),("format","text")]
    out_trans = _lt_post(endpoint, j, f)
    if len(out_trans)!=len(payload_q): raise RuntimeError("LT length mismatch")
    out_lines = list(lines)
    for pos, translated, tags in zip(idx_map, out_trans, tags_list):
        out_lines[pos] = _restore_tags(translated, tags)
    return out_lines

# ---------- CT2 remote ----------
def _ct2_translate_lines(lines: List[str], source: str, target: str, endpoint: str) -> List[str]:
    payload_q, tags_list, idx_map = [], [], []
    for i, line in enumerate(lines):
        if not line.strip(): continue
        protected, tags = _protect_tags(line)
        payload_q.append(protected); tags_list.append(tags); idx_map.append(i)
    if not payload_q: return lines
    r = requests.post(f"{endpoint.rstrip('/')}/translate", json={"q": payload_q, "source": source, "target": target}, timeout=300)
    res = r.json()
    if not r.ok:
        if isinstance(res, dict) and "detail" in res: raise RuntimeError(f"CT2 error: {res['detail']}")
        raise RuntimeError("CT2 request failed")
    out = res.get("translatedText")
    if not isinstance(out, list): raise RuntimeError("CT2 response shape")
    out_lines = list(lines)
    for pos, translated, tags in zip(idx_map, out, tags_list):
        out_lines[pos] = _restore_tags(translated, tags)
    return out_lines

# ---------- Public API ----------
def translate_srt(
    srt_bytes: bytes,
    source: str = "en",
    target: str = "nb",
    engine: str = "auto",  # "argos" | "libre" | "ct2" | "auto"
    libre_endpoint: Optional[str] = None,
    libre_api_key: Optional[str] = None,
    ct2_endpoint: Optional[str] = None,
) -> bytes:
    s = srt_bytes.decode("utf-8-sig", errors="replace")
    subs = list(srt.parse(s, ignore_errors=True))

    use_engine = engine
    if engine == "auto":
        use_engine = "ct2" if ct2_endpoint else ("libre" if libre_endpoint else "argos")

    new_subs = []
    for item in subs:
        lines = _split_keep_newlines(item.content or "")
        if use_engine == "ct2":
            lines_t = _ct2_translate_lines(lines, source, target, ct2_endpoint or "http://ct2:6000")
        elif use_engine == "libre":
            lines_t = _lt_translate_lines(lines, source, target, libre_endpoint or "http://libretranslate:5000", libre_api_key)
        else:
            lines_t = _argos_translate_lines(lines, source, target)
        item.content = _join_with_newlines(lines_t)
        new_subs.append(item)

    out = srt.compose(new_subs)
    return out.encode("utf-8")
