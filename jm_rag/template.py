"""Deterministic answer built from the evidence, used when no model is available or the model keeps failing.

A short cited list of the most relevant facts. Every value is copied from the source record or text, so the
result passes ``post_check``. It adds nothing that is not in the sources.
"""
from __future__ import annotations

import re

from jm_rag.guardrails.sanitize import WITHHELD_TEXT, looks_like_instruction
from jm_rag.notes import record_of

MAX_ITEMS = 5
MAX_FACTS = 8
MAX_VALUE = 80
MAX_SNIPPET = 220
_SKIP_KEYS = {"ocr_raw_json", "image_path", "flags_json", "extraction_flags", "emp_code", "reviewer"}


def _short(value: str, limit: int) -> str:
    if looks_like_instruction(value):
        return WITHHELD_TEXT
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def _facts(source: dict) -> str:
    if source.get("source_type") == "computed_facts":
        return str(source["text"]).strip()
    record = record_of(source)
    parts = []
    for key, value in record.items():
        if key in _SKIP_KEYS or value in (None, "") or isinstance(value, (dict, list)):
            continue
        parts.append(f"{key}={_short(str(value), MAX_VALUE)}")
        if len(parts) >= MAX_FACTS:
            break
    if parts:
        return "; ".join(parts)
    text = str(source.get("text") or "")
    brace = text.find("{")
    return _short(text[:brace] if brace != -1 else text, MAX_SNIPPET).rstrip(".")


def build_template_answer(sources: list[dict], question: str = "") -> str:
    """A cited, evidence-only answer. ``sources`` are the retrieved sources (each with an id)."""
    usable = [source for source in sources if source.get("id") and str(source.get("text") or "").strip()]
    if not usable:
        return ("I could not find evidence to answer that question. "
                "Specify an asset tag, report ID or SOP topic and I will look again.")
    lines = ["Here is what the retrieved records show (no AI wording was generated):", ""]
    computed = [source for source in usable if source.get("source_type") == "computed_facts"]
    for source in [s for s in usable if s.get("source_type") != "computed_facts"][:MAX_ITEMS] + computed:
        title = re.sub(r"\s+", " ", str(source.get("title") or "")).strip()
        label = " (unverified OCR)" if "UNVERIFIED" in str(source.get("text") or "")[:40] else ""
        facts = _facts(source)
        detail = f": {facts}" if facts else ""
        lines.append(f"- {title}{label}{detail} [{source['id']}]")
    lines.append("")
    lines.append("These are the records themselves; see the evidence panel for the full text.")
    return "\n".join(lines)
