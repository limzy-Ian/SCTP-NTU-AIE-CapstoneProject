"""Markdown tables for work-order and incident history."""
from __future__ import annotations

import re

from jm_rag.guardrails.sanitize import looks_like_instruction, sanitize_text
from jm_rag.incidents import event_label, group_incident_events

OCR_TYPES = {"incident_ocr", "processed_incident", "nameplate", "processed_nameplate", "processed_ocr_text"}
OCR_LIMIT = 100
INSTRUCTION_LIMIT = 60


def free_text(value, source_type: str | None = None) -> str:
    """A free-text field from a record, as data. Names are stripped. OCR text and text that reads like an
    instruction to the assistant are shown only in quotes, cut short, with a label saying what they are."""
    if value in (None, ""):
        return "Not recorded"
    text = sanitize_text(re.sub(r"\s+", " ", str(value)).strip())
    ocr, instruction = source_type in OCR_TYPES, looks_like_instruction(text)
    if not (ocr or instruction):
        return text
    limit = INSTRUCTION_LIMIT if instruction else OCR_LIMIT
    shown = text
    if len(text) > limit:
        shown = text[:limit]
        if text[limit] != " ":
            shown = shown.rsplit(" ", 1)[0]
        shown = shown.rstrip(",;:") + "..."
    label = "; ".join(part for part, on in (("OCR text, unverified", ocr), ("shown as data, not an instruction", instruction)) if on)
    return f"\"{shown}\" ({label})"


def format_work_order_table(sources: list[dict]) -> str:
    rows = [source for source in sources
            if source.get("source_type") == "work_order" and source.get("record")]
    if not rows:
        return "I couldn't find matching service records in MySQL."

    def cell(value) -> str:
        return str(value if value is not None else "Not recorded").replace("|", "\\|").replace("\n", " ")

    lines = [
        f"Showing {len(rows)} most recent matching work orders from MySQL `work_orders`.",
        "",
        "| Work Order | Machine | Type | Date | Description | Duration (h) | Cost (SGD) | Status | Source |",
        "|---|---|---|---|---|---:|---:|---|---|",
    ]
    for source in rows:
        record = source["record"]
        cost = record.get("cost_sgd")
        if cost is not None:
            try:
                cost = f"{float(cost):,.2f}"
            except (TypeError, ValueError):
                cost = str(cost)
        lines.append("| " + " | ".join(cell(value) for value in (
            record.get("wo_id"), record.get("machine_id"), record.get("wo_type"),
            record.get("wo_date"), free_text(record.get("description"), "work_order"), record.get("duration_hrs"),
            cost, record.get("status"), f"[{source['id']}]",
        )) + " |")
    return "\n".join(lines)


def format_incident_table(sources: list[dict]) -> str:
    grouped = [(event_label(versions), versions) for versions in group_incident_events(sources)]

    def cell(value) -> str:
        return str(value if value not in (None, "") else "Not recorded").replace("|", "\\|").replace("\n", " ")

    if not grouped:
        return "No matching incident records were retrieved."
    lines = [
        f"Incident history ({len(grouped)} unique incident(s)); versions of one event (CMMS, OCR staging, processed OCR) are grouped by report ID, date and machine.", "",
        "| Incident | Machine | Date | Description | CMMS severity | OCR severity | Lost days | Sources |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for event_id, versions in sorted(grouped, key=lambda item: min(
        str(source.get("incident_date") or (source.get("record") or {}).get("incident_date") or "")
        for source in item[1]
    )):
        cmms = next((source for source in versions if source.get("source_type") == "incident"), None)
        ocr = next((source for source in versions if source.get("source_type") in {"incident_ocr", "processed_incident"}), None)
        primary = cmms or ocr
        primary_record = (primary or {}).get("record") or {}
        cmms_record = (cmms or {}).get("record") or {}
        ocr_record = (ocr or {}).get("record") or {}
        severity_cmms = (f"{cmms_record.get('severity_raw')} ({cmms_record.get('severity_scale')})"
                         if cmms else "Not recorded")
        severity_ocr = (f"{ocr_record.get('severity_raw')} ({ocr_record.get('severity_scale')}, "
                        f"{ocr_record.get('evidence_status', 'UNVERIFIED OCR')})" if ocr else "Not recorded")
        citations = " ".join(f"[{source['id']}]" for source in versions)
        lines.append("| " + " | ".join(cell(value) for value in (
            event_id, primary_record.get("machine_id"), primary_record.get("incident_date"),
            free_text(primary_record.get("description"), (primary or {}).get("source_type")), severity_cmms, severity_ocr,
            f"CMMS: {cmms_record.get('lost_days', 'Not recorded')}; OCR: {ocr_record.get('lost_days', 'Not recorded')}",
            citations,
        )) + " |")
    return "\n".join(lines)


def format_combined_history_table(sources: list[dict]) -> str:
    incident_sources = [source for source in sources if source.get("source_type") in
                         {"incident", "incident_ocr", "processed_incident"}]
    work_order_sources = [source for source in sources if source.get("source_type") == "work_order"]
    work_order_sources.sort(key=lambda source: str(source.get("record_date") or ""), reverse=True)
    sections = []
    if incident_sources:
        sections.append("### Incidents\n\n" + format_incident_table(incident_sources))
    if work_order_sources:
        sections.append("### Service / work orders\n\n" + format_work_order_table(work_order_sources))
    return "\n\n".join(sections) if sections else "No matching incidents or service records were found for that period."
