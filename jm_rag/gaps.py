"""Gaps the data cannot fill, found by code. Each gap adds a note and makes the outcome ``abstain``.

- a nameplate field that the OCR did not read, or read as an implausible value (WELD-01 "2000 kg" capacity);
- an SOP asked for on a topic that none of the SOPs covers ("hot work or welding");
- whether two employee codes are the same person, which the data cannot confirm.
Only values that the code found are stated; nothing is guessed.
"""
from __future__ import annotations

import json
import re

from jm_rag.notes import record_of

FIELD_QUESTIONS = (
    ("grease_interval_hours", "grease interval", r"\bgrease\s+(?:interval|every)|\bgreasing\s+interval|\bhow often\b.{0,30}\bgrease"),
    ("lubricant", "lubricant", r"\b(?:oils?|lubricants?|lubes?|lubrication)\b"),
    ("capacity_raw", "capacity", r"\b(?:capacity|max(?:imum)?\s+load|rated\s+load|swl|safe working load)\b"),
    ("serial_number", "serial number", r"\bserial\b"),
    ("power_kw", "power rating", r"\bpower\b|\bkw\b"),
)
SUSPECT_CODES = {"capacity_raw": {"SUSPECT_CAPACITY_UNIT", "SUSPECT_WELDER_CAPACITY"}}
_SOP_REQUEST = re.compile(r"\b(?:sops?|procedures?|instructions?)\s+(?:for|on|about|covering)\s+(.+?)\s*(?:\?|$)", re.I)
_GENERIC = {"work", "machine", "machines", "using", "with", "doing", "this", "that", "jobs", "tasks", "task", "safety"}
_IDENTITY = re.compile(r"\bsame\s+(?:person|people|employee|worker)\b|\bduplicate\s+(?:employees?|persons?|people|records?)\b", re.I)


def _flag_codes(record: dict) -> set[str]:
    raw = record.get("flags_json")
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        return set()
    return {str(item.get("code")) for item in items if isinstance(item, dict)}


RAW_PATTERNS = {
    "lubricant": re.compile(r"\b\w*BRICANT\W+([^\n]{3,30})", re.I),
    "grease_interval_hours": re.compile(r"\bGREASE\s+INTERVAL\W+(\d[\d,]*\s*h)\b", re.I),
}


def raw_reading(field: str, text: str) -> str | None:
    """The value next to the field's label in raw OCR text, when the structured parser missed it."""
    pattern = RAW_PATTERNS.get(field)
    match = pattern.search(text or "") if pattern else None
    return match.group(1).strip() if match else None


def _raw_source(tag: str, sources: list[dict], all_sources: list[dict]) -> dict | None:
    for pool in (sources, all_sources):
        for source in pool:
            if source.get("source_type") == "processed_ocr_text" and str(source.get("asset_tag") or "").upper() == tag:
                return source
    return None


def plate_field_gaps(question: str, sources: list[dict], tags: set[str], sop_loads: set[str],
                     all_sources: list[dict] | None = None) -> tuple[list[str], bool]:
    """Notes for nameplate fields the question asks about that the plate does not give, and whether to abstain.

    When the structured OCR field is empty but the raw OCR text of the plate has the value next to its label, that
    reading is reported (unverified) and the question is not abstained; the raw text source is added to the evidence.
    A capacity gap does not abstain when an SOP in the evidence gives that machine's load (the conflict covers it)."""
    plates = {str(s["asset_tag"]).upper(): s for s in sources if s.get("source_type") == "nameplate" and s.get("asset_tag")}
    notes, abstain = [], False
    for field, label, pattern in FIELD_QUESTIONS:
        if not re.search(pattern, question, re.I):
            continue
        for tag in sorted(tags):
            plate = plates.get(tag)
            if plate is None:
                continue
            record = record_of(plate)
            value, codes = record.get(field), _flag_codes(record)
            covered = field == "capacity_raw" and tag in sop_loads
            ref = f"[{plate['id']}]" if plate.get("id") else ""
            if value in (None, ""):
                raw = _raw_source(tag, sources, all_sources or [])
                reading = raw_reading(field, str((raw or {}).get("text") or ""))
                if reading:
                    if raw not in sources:
                        sources.append({**raw, "id": f"S{len(sources) + 1}"})
                        raw = sources[-1]
                    raw_ref = f"[{raw['id']}]" if raw.get("id") else ""
                    notes.append(f"The structured nameplate field for the {tag} {label} is empty {ref}, but the raw OCR text of "
                                 f"the plate reads \"{reading}\" next to the label {raw_ref}. This is unverified OCR; check the plate image.")
                    continue
                notes.append(f"The {tag} nameplate OCR did not read a {label} {ref}, so I cannot give it from the plate. "
                             "Check the plate image or the OCR review queue.")
                abstain = abstain or not covered
            elif SUSPECT_CODES.get(field, set()) & codes:
                flagged = ", ".join(sorted(SUSPECT_CODES[field] & codes))
                notes.append(f"The {tag} nameplate {label} reading ({value}) {ref} is flagged as implausible ({flagged}), "
                             f"so it is not reported as the machine's {label}.")
                abstain = abstain or not covered
    return notes, abstain


_SHIFT = re.compile(r"\b(?:night|day)\s*shifts?\b|\bat night\b|\bduring the (?:night|day)\b|\bovernight\b", re.I)
_SENSOR_TYPES = {"sensor_summary", "sensor_trend_monthly", "processed_sensor_summary"}


def shift_gap(question: str, sources: list[dict]) -> str | None:
    """The sensor evidence is per month (or whole period), never per shift or hour of day."""
    if not _SHIFT.search(question) or not any(s.get("source_type") in _SENSOR_TYPES for s in sources):
        return None
    return ("The sensor evidence is summarised by month, not by shift or hour of day, so I cannot say whether the change "
            "is limited to the night shift or also happens by day. The Sensor Trends tab plots the hourly readings.")


def sop_topic_gap(question: str, all_sources: list[dict]) -> str | None:
    """A note when an SOP is asked for on a topic that no SOP in the data mentions."""
    match = _SOP_REQUEST.search(question)
    if not match:
        return None
    topic = match.group(1)
    phrases = [phrase.lower() for phrase in re.findall(r"\b[a-z]{3,}\s+[a-z]{3,}\b", topic, re.I)
               if not set(phrase.lower().split()) & {"or", "and", "the"}]
    words = {word.lower() for word in re.findall(r"[A-Za-z]{4,}", topic)} - _GENERIC
    if not words and not phrases:
        return None
    sops = [s for s in all_sources if s.get("source_type") == "document" and str(s.get("title", "")).upper().startswith("SOP")]
    if not sops:
        return None
    text = " ".join(str(s.get("text") or "") for s in sops).lower()
    stems = {word[:5] for word in words}
    if any(phrase in text for phrase in phrases) or any(stem in text for stem in stems):
        return None
    ids = sorted({re.sub(r"\.(txt|md)$", "", str(s["title"]), flags=re.I) for s in sops})
    return (f"None of the SOPs in the data covers {topic.strip()}. The SOPs available are {', '.join(ids)}. "
            "Ask the safety officer for the approved procedure; I do not make one up.")


def identity_gap(question: str, all_sources: list[dict]) -> tuple[str, dict] | None:
    """(note, source) when the question asks whether employee codes are the same person."""
    if not _IDENTITY.search(question):
        return None
    source = next((s for s in all_sources if s.get("source_type") == "employee_data_quality"), None)
    codes = sorted({code.upper() for code in re.findall(r"\bEMP\s?-?\d{3}\b", question, re.I)})
    listed = ", ".join(codes) if codes else "these employee codes"
    if source is None:
        return (f"I cannot confirm whether {listed} are the same person; the employee data-quality check is unavailable.", None)
    return (f"I cannot confirm whether {listed} are the same person. The employees table lists codes that share a full "
            "name as a possible duplicate, but a shared name does not prove one person, and names are withheld.", source)
