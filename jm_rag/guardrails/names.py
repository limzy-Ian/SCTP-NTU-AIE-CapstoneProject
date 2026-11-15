"""Name and identifier screening, shared by the input guard, output guard and source sanitising.

Full employee names are read from data/guard/name_terms.json, written by
scripts/build_guard_terms.py from the CMMS ``employees`` table. Matched text is never
returned or logged; callers get a placeholder or a short label for the kind of leak.

If the term file is missing or empty the screening cannot see names. That state is
reported (``names_status()``, one log line, the ``names_unloaded`` flag) and never hidden.
"""
from __future__ import annotations

import json
import logging
import re

from jm_rag import config

LOGGER = logging.getLogger("jm_rag.guardrails")

NRIC = re.compile(r"\b[STFGMstfgm]\d{7}[A-Za-z]\b")
API_KEY = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b")
# Internal markers: the employees table, SQL fragments and the system prompt. Table names that the
# app already cites as sources (work_orders, safety_incidents, ...) are not markers.
LEAK_MARKERS = [
    re.compile(r"\bemp_name\b", re.I),
    re.compile(r"\bname_terms\b", re.I),
    re.compile(r"\b(from|join|into|update)\s+`?employees`?\b", re.I),
    re.compile(r"system prompt", re.I),
    re.compile(r"\bselect\b[^.\n]{0,80}\bfrom\b", re.I),
    re.compile(r"\binsert\s+into\b|\bdelete\s+from\b|\bdrop\s+table\b|\bupdate\s+\w+\s+set\b", re.I),
]

NAMES_UNLOADED_FLAG = "names_unloaded"

_override: list[str] | None = None
_cache: dict = {"key": None, "pattern": None}
_warned = False


def _read_terms() -> list[str] | None:
    path = config.guard_terms_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list):
        return None
    return [str(term) for term in terms if str(term).strip()]


def _compile(terms: list[str]) -> re.Pattern | None:
    if not terms:
        return None
    # longest first; whitespace inside a name may vary
    alternatives = sorted((re.escape(term.strip()).replace(r"\ ", r"\s+") for term in terms), key=len, reverse=True)
    return re.compile(r"(?<!\w)(" + "|".join(alternatives) + r")(?!\w)", re.I)


def _pattern() -> re.Pattern | None:
    global _warned
    if _override is not None:
        key = ("override", tuple(_override))
        terms = _override
    else:
        path = config.guard_terms_path()
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            key = (str(path), None)
        terms = None
    if _cache["key"] != key:
        if terms is None:
            terms = _read_terms() if key[1] is not None else None
        _cache["key"], _cache["pattern"] = key, _compile(terms or [])
    pattern = _cache["pattern"]
    if pattern is None and not _warned:
        _warned = True
        LOGGER.warning("Guard name list is missing or empty (%s); names cannot be screened. "
                       "Run scripts/build_guard_terms.py.", NAMES_UNLOADED_FLAG)
    return pattern


def set_terms(terms: list[str] | None) -> None:
    """Use an in-memory term list (tests). Pass None to go back to the file."""
    global _override, _warned
    _override = None if terms is None else list(terms)
    _warned = False
    _cache["key"] = None


def reload() -> None:
    global _warned
    _warned = False
    _cache["key"] = None


def terms_loaded() -> bool:
    return _pattern() is not None


def names_status() -> dict:
    """{"loaded": bool, "flags": [...]} so callers can add the flag to a trace and warn in the UI."""
    loaded = terms_loaded()
    return {"loaded": loaded, "flags": [] if loaded else [NAMES_UNLOADED_FLAG]}


def contains_name(text: str) -> bool:
    pattern = _pattern()
    return bool(pattern and pattern.search(text or ""))


def strip_names(text: str) -> str:
    """Replace full names, national ID numbers and API keys with placeholders."""
    out = text or ""
    pattern = _pattern()
    if pattern:
        out = pattern.sub("[name]", out)
    out = NRIC.sub("[id]", out)
    return API_KEY.sub("[key]", out)


def leak_reason(text: str) -> str | None:
    """Return a short label for the first kind of leak found, never the text itself."""
    if contains_name(text):
        return "name"
    if NRIC.search(text or ""):
        return "national_id"
    if API_KEY.search(text or ""):
        return "api_key"
    for marker in LEAK_MARKERS:
        if marker.search(text or ""):
            return "marker"
    return None
