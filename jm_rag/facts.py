"""Counts, totals, minima, maxima and date ranges, computed in code and offered as an evidence source.

The model is bad at arithmetic and the number check rejects any figure that is not in a cited source.
So the code computes the figures over *all* matching records (not just the few that fit the prompt),
writes them into one source titled "Computed facts" with its own [S#], and the model cites that.
A number the model invents still fails the check, because it is in no source.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date

from jm_rag.incidents import group_incident_events
from jm_rag.notes import record_of
from jm_rag.retrieval import matching_records

TITLE = "Computed facts (calculated by code)"
LOCATION = "Computed in code from the matching records; not retrieved text"


def _number(value) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _day(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _plain(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value != int(value) else f"{int(value):,}"


def _counts(items) -> str:
    return ", ".join(f"{key} {count}" for key, count in sorted(Counter(items).items(), key=lambda pair: str(pair[0])))


def _scope(tags: set[str], window) -> str:
    where = ", ".join(sorted(tags)) if tags else "all machines"
    when = f"{window[0]:%Y-%m-%d} to {(window[1] - date.resolution):%Y-%m-%d}" if window else "any date"
    return f"{where}, {when}"


def work_order_facts(records: list[dict], scope: str) -> str | None:
    rows = [source["record"] for source in records if isinstance(source.get("record"), dict)]
    if not rows:
        return None
    days = [d for d in (_day(row.get("wo_date")) for row in rows) if d]
    costs = [c for c in (_number(row.get("cost_sgd")) for row in rows) if c is not None]
    hours = [h for h in (_number(row.get("duration_hrs")) for row in rows) if h is not None]
    parts = [f"Work orders ({scope}): {len(rows)} in total"]
    if days:
        parts.append(f"dated {min(days)} to {max(days)}")
    if costs:
        parts.append(f"total cost {_money(sum(costs))} SGD (lowest {_money(min(costs))}, highest {_money(max(costs))}; "
                     f"cost recorded for {len(costs)} of {len(rows)})")
    if hours:
        parts.append(f"total duration {_plain(sum(hours))} hours")
    parts.append(f"by type: {_counts(row.get('wo_type') for row in rows)}")
    parts.append(f"by status: {_counts(row.get('status') for row in rows)}")
    if len({row.get("machine_id") for row in rows}) > 1:
        parts.append(f"by machine: {_counts(row.get('machine_id') for row in rows)}")
    return "; ".join(parts) + "."


def incident_facts(records: list[dict], scope: str) -> str | None:
    events = group_incident_events(records)
    if not events:
        return None
    days, lost, scales = [], [], {}
    for versions in events:
        preferred = next((v for v in versions if v.get("source_type") == "incident"), versions[0])
        row = record_of(preferred)
        day = _day(row.get("incident_date") or preferred.get("incident_date"))
        if day:
            days.append(day)
        value = _number(row.get("lost_days"))
        if value is not None:
            lost.append(value)
        scales.setdefault(row.get("severity_scale") or "UNKNOWN", []).append(row.get("severity_raw"))
    parts = [f"Incidents ({scope}): {len(events)} unique incidents from {len(records)} source versions "
             "(CMMS, OCR staging and processed OCR versions of one event are counted once)"]
    if days:
        parts.append(f"dated {min(days)} to {max(days)}")
    if lost:
        parts.append(f"total lost days {_plain(sum(lost))} (highest single incident {_plain(max(lost))})")
    for scale, values in sorted(scales.items()):
        label = {"OLD_1_WORST": "before 1 Jul 2025, 1 is worst", "NEW_5_WORST": "from 1 Jul 2025, 5 is worst"}.get(scale, scale)
        counts = Counter(v for v in values if v is not None)
        shown = ", ".join(f"severity {raw}: {count} incident(s)"
                          for raw, count in sorted(counts.items(), key=lambda pair: str(pair[0])))
        parts.append(f"{scale} scale ({label}): {shown}")
    return "; ".join(parts) + ". Severity numbers are not comparable across the two scales."


_MONTH_LINE = re.compile(r"(\d{4}-\d{2}): (\d+) observed readings")


def sensor_facts(records: list[dict]) -> list[str]:
    lines = []
    for source in records:
        months = []
        for line in re.split(r"(?=\d{4}-\d{2}: \d+ observed readings)", str(source.get("text") or "")):
            head = _MONTH_LINE.match(line.strip())
            if not head:
                continue
            values = {name: _number(m.group(1)) for name, pattern in (
                ("vib_mean", r"mean vibration ([\d.]+)"), ("vib_max", r"maximum vibration ([\d.]+)"),
                ("temp_mean", r"mean temperature ([\d.]+)"), ("temp_max", r"maximum temperature ([\d.]+)"))
                if (m := re.search(pattern, line))}
            months.append((head.group(1), values))
        if not months:
            continue
        parts = [f"Sensor months for {source.get('asset_tag') or source.get('title')}: {len(months)} months, "
                 f"{months[0][0]} to {months[-1][0]}"]
        for key, label, unit in (("vib_mean", "mean vibration", "mm/s"), ("vib_max", "maximum vibration", "mm/s"),
                                 ("temp_mean", "mean temperature", "C"), ("temp_max", "maximum temperature", "C")):
            have = [(month, values[key]) for month, values in months if key in values]
            if have:
                low, high = min(have, key=lambda pair: pair[1]), max(have, key=lambda pair: pair[1])
                parts.append(f"{label} lowest {low[1]:g} {unit} ({low[0]}), highest {high[1]:g} {unit} ({high[0]})")
        lines.append("; ".join(parts) + ".")
    return lines


def spares_facts(records: list[dict], scope: str) -> str | None:
    rows = []
    for source in records:
        text = str(source.get("text") or "")
        marker = text.find("Source row:")
        if marker == -1:
            continue
        try:
            row, _ = json.JSONDecoder().raw_decode(text[text.find("{", marker):])
        except ValueError:
            continue
        rows.append(row)
    if not rows:
        return None
    quantities = [q for q in (_number(row.get("Qty")) for row in rows) if q is not None]
    costs = [c for c in (_number(row.get("Unit Cost")) for row in rows) if c is not None]
    below = [str(row.get("Part No") or row.get("Part Number") or row.get("SKU")) for row in rows
             if _number(row.get("Qty")) is not None and _number(row.get("Min Qty")) is not None
             and _number(row.get("Qty")) < _number(row.get("Min Qty"))]
    parts = [f"Spare parts ({scope}): {len(rows)} rows"]
    if quantities:
        parts.append(f"total quantity in stock {_plain(sum(quantities))}")
    parts.append(f"{len(below)} below minimum quantity" + (f" ({', '.join(below)})" if below else ""))
    if costs:
        parts.append(f"unit cost from {_money(min(costs))} to {_money(max(costs))}")
    return "; ".join(parts) + ". Lead times are text in the workbook and are not summed."


def facts_source(question: str, all_sources: list[dict]) -> dict | None:
    """One evidence source holding the computed facts for the question, or None when nothing applies."""
    groups = matching_records(question, all_sources)
    if not groups:
        return None
    scope = _scope(groups.pop("tags", set()), groups.pop("window", None))
    lines = []
    for kind, records in groups.items():
        if not records:
            continue
        if kind == "work_order":
            line = work_order_facts(records, scope)
        elif kind == "incident":
            line = incident_facts(records, scope)
        elif kind == "sensor":
            lines.extend(sensor_facts(records))
            continue
        else:
            line = spares_facts(records, scope)
        if line:
            lines.append(line)
    if not lines:
        return None
    text = ("Facts computed by code from all matching records, not only the ones shown. "
            "Use these for counts, totals, minima, maxima and date ranges. " + " ".join(lines))
    return {"title": TITLE, "text": text, "location": LOCATION, "source_type": "computed_facts"}
