"""Markdown tables for work-order and incident history."""
from __future__ import annotations


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
            record.get("wo_date"), record.get("description"), record.get("duration_hrs"),
            cost, record.get("status"), f"[{source['id']}]",
        )) + " |")
    return "\n".join(lines)


def format_incident_table(sources: list[dict]) -> str:
    incident_types = {"incident", "incident_ocr", "processed_incident"}
    grouped = {}
    for source in sources:
        if source.get("source_type") not in incident_types:
            continue
        record = source.get("record") or {}
        report_number = source.get("record_key") or record.get("report_no")
        if report_number:
            event_id = str(report_number).rsplit("-", 1)[-1]
        else:
            event_id = str(source.get("incident_id") or record.get("incident_id") or "")
        if not event_id:
            continue
        grouped.setdefault(event_id, []).append(source)

    def cell(value) -> str:
        return str(value if value not in (None, "") else "Not recorded").replace("|", "\\|").replace("\n", " ")

    if not grouped:
        return "No matching incident records were retrieved."
    lines = [
        f"Incident history ({len(grouped)} unique incident(s)); OCR variants are grouped by incident ID.", "",
        "| Incident | Machine | Date | Description | CMMS severity | OCR severity | Lost days | Sources |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for event_id, versions in sorted(grouped.items(), key=lambda item: min(
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
            primary_record.get("description"), severity_cmms, severity_ocr,
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
