"""Conflicts computed in code where the repo already holds both sides.

Each conflict is ``{"kind", "disagrees", "text"}``. ``disagrees`` is True when two sources in the
evidence disagree or cannot be reconciled (this makes the outcome ``conflict``); False for an
informational note, such as one incident held in several sources. Order of trust when sources
disagree: SOP, then nameplate, then CMMS free text. Both sides are always shown. ``ALL`` in the
spares list is never expanded to machines.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from jm_rag.intents import is_incident_query
from jm_rag.notes import record_of
from jm_rag.retrieval import SPARES_LIST_QUESTION
from jm_rag.conflicts_records import (
    _incident_versions, _near_miss_with_lost_days, _severity_not_on_form, _sop_event_not_in_records,
)

_PLATE_TYPES = {"nameplate", "processed_nameplate"}


def _alnum(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _tokens(value) -> list[str]:
    return [token for token in re.split(r"[^A-Za-z0-9-]+", str(value).casefold()) if len(token) >= 2]


def loose_match(plate_value, other_value) -> bool:
    """Do two spellings of a model or lubricant agree, allowing for OCR noise?

    Tokens that contain digits (QT-250, VG68) are the identifying part: if the other value has any, one of them
    must appear in the plate text. Without digit tokens, any similar-looking word counts as a match.
    """
    plate_flat = _alnum(plate_value)
    digit_tokens = [_alnum(token) for token in _tokens(other_value) if any(character.isdigit() for character in token)]
    if digit_tokens:
        return any(token and token in plate_flat for token in digit_tokens)
    return any(SequenceMatcher(None, a, b).ratio() >= 0.6 for a in _tokens(plate_value) for b in _tokens(other_value))


def _same_value(first, second) -> bool:
    try:
        return float(str(first).replace(",", "")) == float(str(second).replace(",", ""))
    except ValueError:
        return _alnum(first) == _alnum(second)


def _conflict(kind: str, text: str, disagrees: bool = True, **extra) -> dict:
    return {"kind": kind, "disagrees": disagrees, "text": text, **extra}


def _first_by_tag(sources: list[dict], source_type: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for source in sources:
        if source.get("source_type") == source_type and source.get("asset_tag"):
            found.setdefault(str(source["asset_tag"]).upper(), source)
    return found


def _ref(source: dict) -> str:
    return f"[{source['id']}]" if source.get("id") else f"({source.get('title')})"


_FIELD_WORDS = {
    "model": r"\bmodel\b", "serial_number": r"\bserial\b", "manufacturer": r"\b(manufacturer|make|maker)\b",
    "lubricant": r"\b(oils?|lubricants?|lubrication|lubes?)\b", "power_kw": r"\b(power|kw|kilowatt)\b",
}
_GENERIC_PLATE = re.compile(r"\b(nameplate|name plate|plate|spec|specs|specification|specifications|details|summary|everything)\b", re.I)


def _field_asked(field: str, question: str) -> bool:
    return bool(_GENERIC_PLATE.search(question) or re.search(_FIELD_WORDS.get(field, r"$^"), question, re.I))


def find_conflicts(sources: list[dict], question: str | None = None, all_sources: list[dict] | None = None) -> list[dict]:
    """All conflicts in the evidence. With a question, only those about what was asked are kept."""
    found = (_plate_vs_cmms_model(sources) + _plate_vs_processed(sources) + _lubricant_vs_all(sources, all_sources)
             + _sop_crane_vs_plate(sources) + _incident_versions(sources)
             + (_spares_all_unresolved(sources) if question and SPARES_LIST_QUESTION.search(question) else [])
             + _near_miss_with_lost_days(sources) + _severity_not_on_form(sources)
             + _sop_event_not_in_records(sources, all_sources))
    if question is None:
        return found
    wanted = []
    for item in found:
        kind = item["kind"]
        if kind == "nameplate_vs_cmms_model" and not _field_asked("model", question):
            continue
        if kind == "nameplate_staging_vs_processed" and not _field_asked(item.get("field", ""), question):
            continue
        if kind == "lubricant_vs_spares_all" and not _field_asked("lubricant", question):
            continue
        if kind == "sop_crane_vs_nameplate" and not re.search(r"\b(load|capacity|tonnage|swl|rated|lift|lifting|crane)\b", question, re.I):
            continue
        if kind == "incident_versions" and not is_incident_query(question):
            continue
        if kind == "sop_event_not_in_records" and not SOP_EVENT_TOPIC.search(question):
            continue
        if kind == "severity_not_on_form" and not re.search(r"\b(severity|severe|reliable|reliability|trust|accurate|correct)\b", question, re.I):
            continue
        wanted.append(item)
    return wanted


def _plate_vs_cmms_model(sources: list[dict]) -> list[dict]:
    found = []
    for tag, source in _first_by_tag(sources, "nameplate").items():
        record = record_of(source)
        plate, cmms = record.get("model"), record.get("cmms_model")
        if plate and cmms and not loose_match(plate, cmms):
            found.append(_conflict(
                "nameplate_vs_cmms_model",
                f"Conflict for {tag}: the nameplate OCR model ({plate}) differs from the CMMS model ({cmms}) {_ref(source)}. "
                "The nameplate is the preferred source over CMMS, but it is unverified OCR, so check the plate image. "
                "Both values are shown."))
    return found


def _plate_vs_processed(sources: list[dict]) -> list[dict]:
    staging = _first_by_tag(sources, "nameplate")
    processed = _first_by_tag(sources, "processed_nameplate")
    found = []
    for tag in sorted(set(staging) & set(processed)):
        a, b = record_of(staging[tag]), record_of(processed[tag])
        for field in ("model", "serial_number", "manufacturer", "lubricant", "power_kw"):
            va, vb = a.get(field), b.get(field)
            if va and vb and not _same_value(va, vb):
                found.append(_conflict(
                    "nameplate_staging_vs_processed",
                    f"Conflict for {tag}: the {field} differs between MySQL nameplate staging ({va}) {_ref(staging[tag])} "
                    f"and the processed OCR ({vb}) {_ref(processed[tag])}. A human-reviewed value would take priority; "
                    "until the image is reviewed neither is trusted.", field=field))
                break
    return found


def _all_spare_description(source: dict) -> str:
    match = re.search(r"Description:\s*(.*?)\.\s*Machine:", str(source.get("text") or ""), re.S)
    return match.group(1).strip() if match else ""


_GRADE = re.compile(r"\bv?g\s?(\d{2,3})\b", re.I)


def _grade(text: str) -> str | None:
    """ISO viscosity grade (VG32, G32, VG 68) written in the text, or None when OCR left none readable."""
    match = _GRADE.search(str(text))
    return match.group(1) if match else None


def _lubricant_agrees(plate_value: str, spare_text: str) -> bool:
    plate_grade, spare_grade = _grade(plate_value), _grade(spare_text)
    if plate_grade and spare_grade:
        return plate_grade == spare_grade
    return loose_match(spare_text, plate_value)


def _plate_grades(sources: list[dict]) -> dict[str, str]:
    """Machine tag -> readable ISO VG grade from its nameplate OCR (machines with no readable grade are left out)."""
    from jm_rag.gaps import raw_reading

    grades: dict[str, str] = {}
    for source in sources:
        if source.get("source_type") in _PLATE_TYPES and source.get("asset_tag"):
            value = record_of(source).get("lubricant") or ""
            if not value and source.get("source_type") == "processed_ocr_text":
                value = raw_reading("lubricant", str(source.get("text") or "")) or ""
            grade = _grade(value)
            if grade:
                grades.setdefault(str(source["asset_tag"]).upper(), grade)
    return grades


def _lubricant_vs_all(sources: list[dict], all_sources: list[dict] | None = None) -> list[dict]:
    """The spares list has one lubricant row for `ALL` machines. That entry is never a per-machine fact:
    - a plate in the evidence that reads a different lubricant is a direct mismatch;
    - otherwise (the plate agrees, has no readable lubricant, or no plate is in the evidence) it is unresolved
      whenever the nameplates of the plant read more than one grade."""
    spares = [source for source in sources if source.get("source_type") == "tabular"
              and str(source.get("asset_tag") or "").upper() == "ALL"
              and re.search(r"\b(oil|grease|lubric)", str(source.get("text") or ""), re.I)]
    if not spares:
        return []
    spare = spares[0]
    description, spare_text = _all_spare_description(spare), str(spare.get("text") or "")
    plates = {}
    for source in sources:
        if source.get("source_type") in _PLATE_TYPES:
            lubricant = record_of(source).get("lubricant")
            if lubricant:
                plates.setdefault(str(lubricant).strip(), source)
    unmatched = sorted(value for value in plates if not _lubricant_agrees(value, spare_text))
    grades = _plate_grades(all_sources or sources)
    spread = sorted({f"VG{grade}" for grade in grades.values()})
    spread_text = (f" Across the plant the nameplates read {', '.join(spread)} (" + "; ".join(
        f"VG{g}: {', '.join(sorted(t for t, v in grades.items() if v == g))}" for g in sorted(set(grades.values()))) + ")."
        if len(spread) > 1 else "")
    if unmatched:
        return [_conflict(
            "lubricant_vs_spares_all",
            f"Conflict on lubricant: the nameplate value(s) ({', '.join(unmatched)}) do not match the spares list entry for "
            f"`ALL` machines ({description or 'see source'}) {_ref(spare)}.{spread_text}"
            + (" Different nameplates list different lubricants, so one oil does not fit every machine." if len(plates) > 1 or len(spread) > 1 else "")
            + " "
            "`ALL` is left unresolved and is not expanded to machines.")]
    if len(spread) < 2:
        return []
    lead = ("It matches this nameplate, but" if plates else "No nameplate in the evidence confirms it, and")
    spare_grade = _grade(spare_text)
    shown = {str(source.get("asset_tag") or "").upper() for source in plates.values()}
    differ = sorted(tag for tag, grade in grades.items() if tag not in shown and spare_grade and grade != spare_grade)
    return [_conflict(
        "lubricant_vs_spares_all",
        f"Conflict on lubricant: the spares list has one entry for `ALL` machines ({description or 'see source'}) {_ref(spare)}. "
        + (f"{lead} the nameplates of {', '.join(differ[:6])} read a different viscosity grade" if differ else f"{lead} the nameplates do not all read the same grade")
        + f", so `ALL` is not a per-machine fact.{spread_text} "
        "`ALL` is left unresolved and is not expanded to machines; use the machine's own plate.")]


def _spares_all_unresolved(sources: list[dict]) -> list[dict]:
    """A machine's spares answer that includes a row listed for `ALL`: the row is shown but cannot be assigned."""
    rows = [source for source in sources if source.get("source_type") == "tabular"
            and str(source.get("asset_tag") or "").upper() == "ALL"]
    if not rows:
        return []
    parts = ", ".join(f"{re.search(r'Part number: ([^.]+)', str(r.get('text'))).group(1) if re.search(r'Part number: ([^.]+)', str(r.get('text'))) else r.get('title')} {_ref(r)}" for r in rows)
    return [_conflict(
        "spares_all_unresolved",
        f"Unresolved: {parts} is listed for machine `ALL` in the spares list. `ALL` is not resolved to machines, so it is "
        "shown but cannot be confirmed as a spare for this machine. Absence of a part listed for a machine is not evidence "
        "that none is needed.")]


SOP_EVENT_TOPIC = re.compile(r"\b(?:cranes?|slings?|lift\w*|loads?|near.?miss\w*|incidents?|rigging|hoist\w*)\b", re.I)


def _sop_rated_loads(sources: list[dict]) -> dict[str, tuple[float, str]]:
    loads: dict[str, tuple[float, str]] = {}
    for source in sources:
        if source.get("source_type") != "document":
            continue
        for tag, number, unit in re.findall(r"\b(CRN-\d+)\s*=\s*([\d,]+(?:\.\d+)?)\s*(kg|tonnes?|t)\b",
                                            str(source.get("text") or ""), re.I):
            kilograms = float(number.replace(",", "")) * (1 if unit.lower() == "kg" else 1000)
            loads[tag.upper()] = (kilograms, _ref(source))
    return loads


def _plate_kilograms(source: dict) -> float | None:
    match = re.search(r"\b(\d[\d,]*(?:\.\d+)?)\s*(kg|tonnes?|t)\b", str(record_of(source).get("capacity_raw") or ""), re.I)
    if not match:
        return None
    return float(match.group(1).replace(",", "")) * (1 if match.group(2).lower() == "kg" else 1000)


def _sop_crane_vs_plate(sources: list[dict]) -> list[dict]:
    loads = _sop_rated_loads(sources)
    found = []
    plates = {}
    for source in sources:
        if source.get("source_type") in _PLATE_TYPES and str(source.get("asset_tag") or "").upper().startswith("CRN"):
            plates.setdefault(str(source["asset_tag"]).upper(), source)
    for tag, (kilograms, reference) in sorted(loads.items()):
        plate = plates.get(tag)
        if plate is None:
            continue
        plate_kg = _plate_kilograms(plate)
        if plate_kg is None:
            found.append(_conflict(
                "sop_crane_vs_nameplate",
                f"Conflict on {tag} load: the SOP gives a maximum load of {kilograms:,.0f} kg {reference}, but the "
                f"nameplate {_ref(plate)} carries no tonnage, so the two cannot be cross-checked. The SOP is the "
                "controlled document and is the one to rely on; both are shown."))
        elif abs(plate_kg - kilograms) > 0.01 * kilograms:
            found.append(_conflict(
                "sop_crane_vs_nameplate",
                f"Conflict on {tag} load: the SOP gives {kilograms:,.0f} kg {reference}; the nameplate OCR reads "
                f"{plate_kg:,.0f} kg {_ref(plate)} (unverified). The SOP is the controlled document and is trusted; "
                "both are shown."))
    return found


_LUBE_QUESTION = re.compile(r"\b(oils?|lubricants?|lubrication|lubes?)\b", re.I)
_LOAD_QUESTION = re.compile(r"\b(max(?:imum)? load|rated load|swl|safe working load|capacity|tonnage|lifting|lifts?)\b", re.I)
_MONTH_YEAR = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(20\d{2})\b", re.I)
_CRANE_TAG = re.compile(r"\bCRN-\d+\b", re.I)
MAX_EXTRA = 4


def related_sources(question: str, sources: list[dict], all_sources: list[dict]) -> list[dict]:
    """Other sources that must sit beside the retrieved ones for a conflict to be seen.

    A lubricant question needs the `ALL` spares row next to the nameplate; a crane load question needs the
    nameplate next to the SOP. Retrieval ranks by text similarity and may leave the other side out.
    """
    have = {(source.get("title"), source.get("location")) for source in sources}
    extra: list[dict] = []

    def add(candidate: dict) -> None:
        key = (candidate.get("title"), candidate.get("location"))
        if key not in have and len(extra) < MAX_EXTRA:
            have.add(key)
            extra.append(candidate)

    if _LUBE_QUESTION.search(question):
        for candidate in all_sources:
            if (candidate.get("source_type") == "tabular" and str(candidate.get("asset_tag") or "").upper() == "ALL"
                    and re.search(r"\b(oil|grease|lubric)", str(candidate.get("text") or ""), re.I)):
                add(candidate)
    if _LOAD_QUESTION.search(question):
        tags = {tag.upper() for tag in _CRANE_TAG.findall(question)}
        tags |= {str(source["asset_tag"]).upper() for source in sources
                 if source.get("source_type") in _PLATE_TYPES and str(source.get("asset_tag") or "").upper().startswith("CRN")}
        for candidate in all_sources:
            if candidate.get("source_type") in _PLATE_TYPES and str(candidate.get("asset_tag") or "").upper() in tags:
                add(candidate)
            elif candidate.get("source_type") == "document" and any(
                    re.search(rf"\b{re.escape(tag)}\s*=", str(candidate.get("text") or ""), re.I) for tag in tags):
                add(candidate)
    if is_incident_query(question):
        # an SOP that mentions an incident in the asked month sits beside the incident records
        for month, year in _MONTH_YEAR.findall(question):
            for candidate in all_sources:
                if candidate.get("source_type") == "document" and re.search(
                        rf"\b{month[:3]}[a-z]*\.?\s+{year}\b[^.\n]{{0,20}}\b(near[\s-]?miss|incident|accident)",
                        str(candidate.get("text") or ""), re.I):
                    add(candidate)
    return extra
