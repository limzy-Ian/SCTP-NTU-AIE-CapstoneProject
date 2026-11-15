"""Conflicts between incident records and other sources (CMMS, OCR of the forms, SOP text).

Split out of conflicts.py to keep modules small; the shapes and rules are the same.
"""
from __future__ import annotations

import re
from datetime import date

from jm_rag.incidents import event_label, group_incident_events
from jm_rag.notes import record_of


def _conflict(kind: str, text: str, disagrees: bool = True, **extra) -> dict:
    return {"kind": kind, "disagrees": disagrees, "text": text, **extra}


def _ref(source: dict) -> str:
    return f"[{source['id']}]" if source.get("id") else f"({source.get('title')})"


_NEAR_MISS = re.compile(r"near[\s-]?miss", re.I)


def _near_miss_with_lost_days(sources: list[dict]) -> list[dict]:
    """A CMMS incident described as a near miss but recorded with lost days: the description and the field disagree."""
    found = []
    for source in sources:
        if source.get("source_type") != "incident":
            continue
        record = source.get("record") or {}
        try:
            lost = float(record.get("lost_days") or 0)
        except (TypeError, ValueError):
            lost = 0
        if lost > 0 and _NEAR_MISS.search(str(record.get("description") or "")):
            found.append(_conflict(
                "near_miss_with_lost_days",
                f"Conflict on incident {source.get('incident_id')}: it is described as a near miss, but {lost:g} lost day(s) "
                f"are recorded {_ref(source)}. A near miss normally has no injury, so one of the two is wrong. Both are shown; "
                "the record needs checking with the safety officer."))
    return found


def _severity_not_on_form(sources: list[dict]) -> list[dict]:
    """CMMS has a severity but the scanned form's OCR has none, so the CMMS value cannot be checked against the form."""
    found = []
    for versions in group_incident_events(sources):
        cmms = next((v for v in versions if v.get("source_type") == "incident"), None)
        forms = [v for v in versions if v.get("source_type") != "incident"]
        if cmms is None or not forms:
            continue
        if (cmms.get("record") or {}).get("severity_raw") is not None and all(
                record_of(form).get("severity_raw") in (None, "") for form in forms):
            refs = " ".join(_ref(form) for form in forms)
            found.append(_conflict(
                "severity_not_on_form",
                f"Incident {event_label(versions)}: the CMMS gives severity {(cmms.get('record') or {}).get('severity_raw')} "
                f"{_ref(cmms)}, but the OCR of the scanned form read no severity {refs}, so the CMMS value cannot be "
                "cross-checked against the form. The CMMS value is used and is marked unverified."))
    return found


_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(20\d{2})"


_STOP = {"after", "were", "with", "that", "this", "from", "have", "slings", "years"}


def _sop_event_not_in_records(sources: list[dict], all_sources: list[dict] | None) -> list[dict]:
    """An SOP mentions a dated incident (\"the Aug 2025 near-miss (sling snapped)\") that the incident records do not hold."""
    pool = all_sources or sources
    found = []
    for source in sources:
        if source.get("source_type") != "document":
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n", str(source.get("text") or "")):
            match = re.search(rf"\b{_MON}\b[^.\n]{{0,20}}\b(near[\s-]?miss|incident|accident)", sentence, re.I)
            if not match:
                continue
            month = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].index(match.group(1).lower()) + 1
            year = int(match.group(2))
            words = {w.lower() for w in re.findall(r"\(([^)]+)\)", sentence) for w in re.findall(r"[A-Za-z]{4,}", w)} - _STOP
            same_month = [s for s in pool if s.get("source_type") == "incident"
                          and str((s.get("record") or {}).get("incident_date") or s.get("incident_date"))[:7] == f"{year:04d}-{month:02d}"]
            matching = [s for s in same_month if words and any(w in str((s.get("record") or {}).get("description") or "").lower() for w in words)]
            if matching:
                continue
            label = date(year, month, 1).strftime("%b %Y")
            found.append(_conflict(
                "sop_event_not_in_records",
                f"Conflict: {source.get('title', 'the SOP').replace('.txt', '')} {_ref(source)} mentions a {match.group(3).lower()} in "
                f"{label}" + (f" ({', '.join(sorted(words))})" if words else "") + f", but the CMMS has {len(same_month)} incident(s) "
                f"in {label} and none of them matches it. I do not invent an incident record; the SOP is the controlled document, "
                "so its statement is reported as it is, and the gap in the incident log is flagged."))
    return found


def _incident_versions(sources: list[dict]) -> list[dict]:
    groups = [(event_label(versions), versions) for versions in group_incident_events(sources)]
    found = []
    for event, versions in sorted(groups, key=lambda item: item[0]):
        if len({version["source_type"] for version in versions}) < 2:
            continue
        differences = []
        for field in ("severity_raw", "lost_days", "incident_date", "machine_id"):
            values = {str(record_of(version).get(field)) for version in versions
                      if record_of(version).get(field) not in (None, "")}
            if len(values) > 1:
                differences.append(field.replace("_", " "))
        refs = " ".join(_ref(version) for version in versions)
        if differences:
            found.append(_conflict(
                "incident_versions",
                f"Conflict on incident {event}: the CMMS, OCR staging and processed OCR versions disagree on "
                f"{', '.join(differences)} {refs}. The CMMS safety_incidents record is authoritative; the OCR versions "
                "are unverified. It is one event and is counted once."))
        else:
            found.append(_conflict(
                "incident_versions",
                f"Incident {event} appears in more than one source {refs}; the versions agree and it is counted once.",
                disagrees=False))
    return found
