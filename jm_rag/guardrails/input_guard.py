"""Input guard: runs first, uses no model, and refuses what the policy forbids.

``check()`` is a pure function returning ``{verdict, class, message, flags, question}``.
Classes are tried in a fixed order, the first match wins:
INJECTION, NAME_REQUEST, PERSON_RANKING, WRITE_INTENT, SAFETY_BYPASS, PRIVATE_DATA,
then (after those) a full employee name in the question, creative requests, and questions
with no domain word and no earlier turn (OFF_TOPIC). EMPTY and TOO_LONG are checked first.
Flags (inference_request, needs_future_date, asks_missing_document, asks_schedule) are set
on passing questions; they never refuse.
"""
from __future__ import annotations

import re

from jm_rag import config
from jm_rag.guardrails import names, patterns

_ORDER = ("INJECTION", "NAME_REQUEST", "PERSON_RANKING", "WRITE_INTENT")
_COMPILED = {cls: [re.compile(p) for p in getattr(patterns, cls)] for cls in _ORDER}
_SAFETY = [re.compile(p) for p in patterns.SAFETY_BYPASS]
_PRIVATE = [re.compile(p) for p in patterns.PRIVATE_DATA]
_CREATIVE = [re.compile(p) for p in patterns.CREATIVE]
_INFERENCE = [re.compile(p) for p in patterns.INFERENCE]
_FUTURE = [re.compile(p) for p in patterns.BARE_FUTURE]
_MISSING_DOC = [re.compile(p) for p in patterns.MISSING_DOCUMENT]
_SCHEDULE = [re.compile(p) for p in patterns.SCHEDULE]

_DATA_END_YM = (config.DATA_END.year, config.DATA_END.month)

#: classes that the legacy ``input_refusal`` and answer-text checks use
TEXT_CLASSES = ("SAFETY_BYPASS", "PRIVATE_DATA")


def _any(regexes: list[re.Pattern], text: str) -> bool:
    return any(regex.search(text) for regex in regexes)


def _safety_bypass(text: str) -> bool:
    """True for bypass wording that is not negated just before the verb ("never bypass the interlock")."""
    for regex in _SAFETY:
        for match in regex.finditer(text):
            before = text[:match.start()]
            if patterns.SAFETY_NOUN_BEFORE.search(before):
                continue
            if not patterns.SAFETY_NEGATION.search(before[-40:]):
                return True
    return False


def detect_future_date(text: str) -> bool:
    """True when the question names a month after the end of the data (30 Jun 2026)."""
    for match in patterns.MONTH_YEAR.finditer(text):
        month = patterns.MONTHS[match.group(1)[:3]]
        if (int(match.group(2)), month) > _DATA_END_YM:
            return True
    for match in patterns.YEAR_MONTH_NUM.finditer(text):
        if (int(match.group(1)), int(match.group(2))) > _DATA_END_YM:
            return True
    return _any(_FUTURE, text)


def detect_flags(text: str) -> dict:
    return {
        "inference_request": _any(_INFERENCE, text),
        "needs_future_date": detect_future_date(text),
        "asks_missing_document": _any(_MISSING_DOC, text),
        "asks_schedule": _any(_SCHEDULE, text),
    }


def _refuse(cls: str, flags: dict | None = None) -> dict:
    return {"verdict": "refuse", "class": cls, "message": patterns.MESSAGES[cls],
            "flags": flags or {}, "question": None}


def classify_text(text: str) -> str | None:
    """First of SAFETY_BYPASS / PRIVATE_DATA matching the text, or None. Used on answer text too."""
    low = (text or "").lower()
    if _safety_bypass(low):
        return "SAFETY_BYPASS"
    if _any(_PRIVATE, low):
        return "PRIVATE_DATA"
    return None


def unsafe_text_message(text: str) -> str | None:
    """Refusal message if the text asks for or describes a safety bypass or private data."""
    cls = classify_text(text)
    return patterns.MESSAGES[cls] if cls else None


def check(question: str | None, has_history: bool = False) -> dict:
    """Return {verdict: pass|refuse, class, message, flags, question}."""
    q = re.sub(r"\s+", " ", (question or "")).strip()
    if not q:
        return _refuse("EMPTY")
    if len(q) > config.max_question_chars():
        return _refuse("TOO_LONG")
    low = q.lower()

    for cls in _ORDER:
        if _any(_COMPILED[cls], low):
            return _refuse(cls)
    cls = classify_text(low)
    if cls:
        return _refuse(cls)
    # a full employee name typed into the question is treated as a request about a person
    if names.contains_name(q):
        return _refuse("NAME_REQUEST")
    if _any(_CREATIVE, low):
        return _refuse("OFF_TOPIC")
    if not has_history and not patterns.DOMAIN.search(low):
        return _refuse("OFF_TOPIC")
    return {"verdict": "pass", "class": None, "message": None, "flags": detect_flags(low), "question": q}


def input_refusal(question: str) -> str | None:
    """Legacy helper kept for callers of the old API: the refusal message, or None to continue.

    Runs the full guard as if the conversation had history (so "hello" is not refused here) and
    does not treat an empty question as a refusal.
    """
    result = check(question, has_history=True)
    if result["verdict"] == "refuse" and result["class"] != "EMPTY":
        return result["message"]
    return None

