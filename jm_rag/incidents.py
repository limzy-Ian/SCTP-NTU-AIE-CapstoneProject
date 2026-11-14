"""Which incident sources describe the same event.

An incident can be held as a CMMS record, an OCR staging record and a processed OCR record. Counting, tables
and conflict checks must count one event once, so they all group through ``group_incident_events``.

Rules (Phase 4b fix 9; before, only the trailing number of the ID was compared):
- OCR staging and processed OCR versions of one report share the report key (``IR-2024-917``) and are one event.
- A report and a CMMS incident are one event when the report number equals the CMMS incident ID **and** the
  report year equals the year of the CMMS incident date **and**, where both sides have a date, the dates are
  equal. A different machine does not split them: that is a disagreement to report, not two events.
- Two CMMS records, or two reports with different keys, are never merged. A machine and date alone never merge
  two records either, because two incidents can happen on one machine on one day.
"""
from __future__ import annotations

import re
from datetime import date

INCIDENT_TYPES = {"incident", "incident_ocr", "processed_incident"}
_REPORT = re.compile(r"^IR-(\d{4})-0*(\d+)$", re.I)


def _report(source: dict) -> tuple[int, int] | None:
    match = _REPORT.match(str(source.get("record_key") or ""))
    return (int(match.group(1)), int(match.group(2))) if match else None


def _cmms_id(source: dict) -> int | None:
    if source.get("source_type") != "incident":
        return None
    try:
        return int(str(source.get("incident_id")))
    except (TypeError, ValueError):
        return None


def _day(source: dict) -> date | None:
    value = source.get("incident_date") or (source.get("record") or {}).get("incident_date")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def same_event(first: dict, second: dict) -> bool:
    """True when two incident sources are versions of one event under the rules above."""
    key_a, key_b = first.get("record_key"), second.get("record_key")
    if key_a and key_a == key_b:
        return True
    for report_source, cmms_source in ((first, second), (second, first)):
        report, cmms = _report(report_source), _cmms_id(cmms_source)
        if report is None or cmms is None or report[1] != cmms:
            continue
        cmms_day, report_day = _day(cmms_source), _day(report_source)
        if cmms_day is None or cmms_day.year != report[0]:
            continue
        if report_day is not None and report_day != cmms_day:
            continue
        return True
    return False


def group_incident_events(sources: list[dict]) -> list[list[dict]]:
    """Incident sources grouped by event, in first-seen order."""
    incidents = [source for source in sources if source.get("source_type") in INCIDENT_TYPES]
    parent = list(range(len(incidents)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, first in enumerate(incidents):
        for j in range(i + 1, len(incidents)):
            if same_event(first, incidents[j]):
                parent[find(j)] = find(i)
    groups: dict[int, list[dict]] = {}
    for index, source in enumerate(incidents):
        groups.setdefault(find(index), []).append(source)
    return list(groups.values())


def event_label(versions: list[dict]) -> str:
    """Short ID shown for an event: the trailing number of its CMMS incident ID or report key."""
    preferred = next((source for source in versions if source.get("source_type") == "incident"), versions[0])
    key = preferred.get("incident_id") or preferred.get("record_key") or preferred.get("title")
    return str(key).rsplit("-", 1)[-1]
