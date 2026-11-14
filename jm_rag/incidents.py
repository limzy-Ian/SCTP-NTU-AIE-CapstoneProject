"""Which incident sources describe the same event.

An incident can be held as a CMMS record, an OCR staging record and a processed OCR record. Counting,
tables and conflict checks must count one event once, so they all group through ``group_incident_events``.
"""
from __future__ import annotations

INCIDENT_TYPES = {"incident", "incident_ocr", "processed_incident"}


def event_key(source: dict) -> str:
    """Trailing number of the report key or CMMS incident ID (``IR-2024-917`` and CMMS ``917`` share ``917``)."""
    key = source.get("record_key") or source.get("incident_id")
    return str(key).rsplit("-", 1)[-1] if key else str(source.get("title") or "")


def group_incident_events(sources: list[dict]) -> list[list[dict]]:
    """Incident sources grouped by event, in first-seen order."""
    groups: dict[str, list[dict]] = {}
    for source in sources:
        if source.get("source_type") in INCIDENT_TYPES:
            groups.setdefault(event_key(source), []).append(source)
    return list(groups.values())
