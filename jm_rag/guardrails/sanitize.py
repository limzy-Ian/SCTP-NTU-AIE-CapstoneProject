"""Remove personal data from evidence before it is shown in the UI or sent to the model.

Applied to every retrieved source (title, text, location and the structured ``record``),
and to chat history shown or replayed. Full employee names, national IDs and API keys are
replaced with placeholders. Fields that hold the reviewer's identity are removed outright:
the ``reviewer`` value from ``ocr_review_decisions`` is personal data and never reaches
evidence text or answers.
"""
from __future__ import annotations

import logging
import re

from jm_rag.guardrails import names, patterns

LOGGER = logging.getLogger("jm_rag.guardrails")

# free text that reads like an instruction to the assistant (prompt injection carried in a record)
_INSTRUCTION_LIKE = [re.compile(pattern) for pattern in patterns.INJECTION]
WITHHELD_TEXT = "[free text withheld: it reads like an instruction]"


def looks_like_instruction(text) -> bool:
    """True when record text matches the injection phrasings. Such text is data, never shown as an instruction."""
    return isinstance(text, str) and any(regex.search(text.lower()) for regex in _INSTRUCTION_LIKE)


# record keys that identify a person; dropped, not masked
PERSONAL_KEYS = {"reviewer", "reviewed_by", "reviewer_name", "emp_name", "employee_name",
                 "injured_person", "injured_name", "reported_by_name", "technician_name"}
_TEXT_KEYS = ("title", "text", "location")
_PERSONAL_JSON = re.compile(
    r'"(?:' + "|".join(sorted(PERSONAL_KEYS)) + r')"\s*:\s*(?:"(?:[^"\\]|\\.)*"|null|\d+)', re.I)


def sanitize_text(text):
    """Strip names, IDs and keys from a string. Non-strings are returned unchanged."""
    if not isinstance(text, str):
        return text
    text = _PERSONAL_JSON.sub('"reviewer": "[removed]"', text)
    return names.strip_names(text)


def _clean_value(value):
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {key: _clean_value(item) for key, item in value.items()
                if str(key).lower() not in PERSONAL_KEYS}
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    return value


def sanitize_source(source: dict) -> dict:
    """Return a cleaned copy of one source dict. The input is not modified."""
    cleaned = dict(source)
    for key in _TEXT_KEYS:
        if key in cleaned:
            cleaned[key] = sanitize_text(cleaned[key])
    if isinstance(cleaned.get("record"), dict):
        cleaned["record"] = _clean_value(cleaned["record"])
    return cleaned


def sanitize_sources(sources: list[dict]) -> list[dict]:
    return [sanitize_source(source) for source in sources]


def sanitize_message(message: dict) -> dict:
    """Clean one saved chat message (content and cited sources) before it is shown or replayed."""
    cleaned = dict(message)
    if "content" in cleaned:
        cleaned["content"] = sanitize_text(cleaned["content"])
    if isinstance(cleaned.get("sources"), list):
        cleaned["sources"] = [sanitize_source(source) if isinstance(source, dict) else source
                              for source in cleaned["sources"]]
    return cleaned
