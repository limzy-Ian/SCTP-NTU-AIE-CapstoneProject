"""Mandatory caveats computed in code and appended to the answer (conflicts are in conflicts.py).

``mandatory_notes`` works from the input-guard flags, the question and the evidence, so the model
cannot leave a caveat out.
"""
from __future__ import annotations

import json
import re
from datetime import date

from jm_rag.config import DATA_END

SEVERITY_FLIP = date(2025, 7, 1)

FUTURE_NOTE = (f"The data ends on {DATA_END:%d %b %Y}, so I cannot answer for later dates or forecast them.")
MISSING_DOCUMENT_NOTE = ("No 5-Why, root-cause or investigation document is in the data, "
                         "even where a form says one is attached.")
SCHEDULE_NOTE = ("The data holds past and open work orders only, so I cannot give the next service or due date.")
INFERENCE_NOTE = ("The data does not record causes, alarm limits or failure history, so this describes what the "
                  "records show; it does not predict a failure or declare a machine safe.")
SEVERITY_NOTE = ("Incident severity changed scale on 1 Jul 2025: before then 1 is worst, from then 5 is worst. "
                 "A plain severity number is not comparable across that date.")
OCR_NOTE = ("Some values come from OCR that is not human-verified; those are labelled unverified and may be wrong.")

_SEVERITY_IN_QUESTION = re.compile(r"\bseverity|worst|most severe|severe\b", re.I)


def _severity_spans_flip(sources: list[dict]) -> bool:
    before = after = False
    for source in sources:
        when = source.get("incident_date")
        if isinstance(when, str):
            try:
                when = date.fromisoformat(when[:10])
            except ValueError:
                when = None
        if isinstance(when, date):
            before = before or when < SEVERITY_FLIP
            after = after or when >= SEVERITY_FLIP
    return before and after


def _has_unverified_ocr(sources: list[dict]) -> bool:
    for source in sources:
        if source.get("source_type") in {"incident_ocr", "processed_incident", "processed_nameplate",
                                          "processed_ocr_text"}:
            return True
        if "UNVERIFIED" in str(source.get("text") or ""):
            return True
    return False


def mandatory_notes(flags: dict, question: str, sources: list[dict]) -> list[str]:
    """Caveats that must be shown, based on the guard flags, the question and the evidence."""
    notes: list[str] = []
    flags = flags or {}
    if flags.get("needs_future_date"):
        notes.append(FUTURE_NOTE)
    if flags.get("asks_missing_document"):
        notes.append(MISSING_DOCUMENT_NOTE)
    if flags.get("asks_schedule"):
        notes.append(SCHEDULE_NOTE)
    if flags.get("inference_request"):
        notes.append(INFERENCE_NOTE)
    if _SEVERITY_IN_QUESTION.search(question or "") and _severity_spans_flip(sources):
        notes.append(SEVERITY_NOTE)
    if _has_unverified_ocr(sources):
        notes.append(OCR_NOTE)
    return notes


def record_of(source: dict) -> dict:
    record = source.get("record")
    if isinstance(record, dict):
        return record
    text = str(source.get("text") or "")
    marker = text.find("Extracted fields:")
    brace = text.find("{", marker if marker != -1 else 0)
    if brace != -1:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[brace:])
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}
