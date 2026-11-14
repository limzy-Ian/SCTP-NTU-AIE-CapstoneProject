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

from jm_rag.config import DATA_END
from jm_rag.incidents import event_label, group_incident_events
from jm_rag.notes import record_of
from jm_rag.retrieval import matching_records

TITLE = "Computed facts (calculated by code)"
LOCATION = "Computed in code from the matching records; not retrieved text"


def _number(value) -> float | None:
    try:
        return float(re.sub(r"^(?:S\$|SGD|\$)\s*", "", str(value).replace(",", "").strip(), flags=re.I))
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
    priced = [row for row in rows if _number(row.get("cost_sgd")) is not None]
    if priced:
        top = max(priced, key=lambda row: _number(row.get("cost_sgd")))
        low = min(priced, key=lambda row: _number(row.get("cost_sgd")))
        parts.append(f"most expensive: work order {top.get('wo_id')} ({_money(_number(top.get('cost_sgd')))} SGD, "
                     f"{top.get('machine_id')}); cheapest: work order {low.get('wo_id')} ({_money(_number(low.get('cost_sgd')))} SGD)")
    parts.append(f"by type: {_counts(row.get('wo_type') for row in rows)}")
    parts.append(f"by status: {_counts(row.get('status') for row in rows)}")
    not_closed = [row for row in rows if str(row.get("status") or "").upper() != "CLOSED"]
    parts.append(f"not closed (open or awaiting parts): {len(not_closed)}")
    if 0 < len(not_closed) <= 15:
        parts.append("not-closed work order IDs: " + ", ".join(str(row.get("wo_id")) for row in
                                                               sorted(not_closed, key=lambda row: str(row.get("wo_date")))))
    if len({row.get("machine_id") for row in rows}) > 1:
        parts.append(f"by machine: {_counts(row.get('machine_id') for row in rows)}")
    if 0 < len(rows) <= 15:
        parts.append("work order IDs: " + ", ".join(str(row.get("wo_id")) for row in sorted(rows, key=lambda row: str(row.get("wo_date")))))
    return "; ".join(parts) + "."


def incident_facts(records: list[dict], scope: str) -> str | None:
    events = group_incident_events(records)
    if not events:
        return None
    days, lost, scales, rows = [], [], {}, []
    for versions in events:
        preferred = next((v for v in versions if v.get("source_type") == "incident"), versions[0])
        row = record_of(preferred)
        rows.append((preferred, row, versions))
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
        parts.append("by year: " + _counts(str(day.year) for day in days))
    if lost:
        parts.append(f"total lost days {_plain(sum(lost))} (highest single incident {_plain(max(lost))})")
    machines = Counter(row.get("machine_id") for _, row, _ in rows if row.get("machine_id"))
    if len(machines) > 1:
        top = machines.most_common(1)[0]
        parts.append(f"by machine: {_counts(machines.elements())}; most incidents: {top[0]} with {top[1]}")
    reporting = Counter(row.get("reporting") for _, row, _ in rows if row.get("reporting"))
    if reporting:
        parts.append("by how reported: " + ", ".join(f"{key} {count}" for key, count in sorted(reporting.items())))
    forms = sum(1 for _, _, versions in rows if any(v.get("source_type") != "incident" for v in versions))
    parts.append(f"with a scanned incident form (OCR record): {forms}")
    for scale, values in sorted(scales.items()):
        label = {"OLD_1_WORST": "before 1 Jul 2025, 1 is worst", "NEW_5_WORST": "from 1 Jul 2025, 5 is worst"}.get(scale, scale)
        counts = Counter(v for v in values if v is not None)
        shown = ", ".join(f"severity {raw}: {count} incident(s)"
                          for raw, count in sorted(counts.items(), key=lambda pair: str(pair[0])))
        parts.append(f"{scale} scale ({label}): {shown}")
    parts += _normalised_severity(rows)
    near = [str(row.get("incident_id") or event_label(versions)) for _, row, versions in rows
            if _number(row.get("lost_days")) and re.search(r"near[\s-]?miss", str(row.get("description") or ""), re.I)]
    if near:
        parts.append(f"recorded as a near miss but with lost days: {len(near)} ({', '.join(sorted(near))})")
    if 0 < len(rows) <= 12:
        parts.append("incident IDs: " + ", ".join(str(row.get("incident_id") or event_label(versions)) for _, row, versions in rows))
    return "; ".join(parts) + ". Severity numbers are not comparable across the two scales."


def _normalised_severity(rows) -> list[str]:
    """Severity on one scale (5 = worst for every year), with the raw counts that would mislead."""
    levels, worst, raw = Counter(), [], Counter()
    for _, row, versions in rows:
        value = _number(row.get("severity_5_worst"))
        if value is None:
            value = _number(row.get("severity_raw"))
            if value is not None and row.get("severity_scale") == "OLD_1_WORST":
                value = 6 - value
        if row.get("severity_raw") is not None:
            raw[_plain(_number(row.get("severity_raw")) or 0)] += 1
        if value is None:
            continue
        levels[int(value)] += 1
        if int(value) == 5:
            worst.append(str(row.get("incident_id") or event_label(versions)))
    if not levels:
        return []
    names = {1: "least severe", 5: "worst"}
    shown = ", ".join(f"level {level}{' (' + names[level] + ')' if level in names else ''}: {count}"
                      for level, count in sorted(levels.items()))
    lines = [f"severity normalised to one scale where 5 is worst for every year (old scale converted as 6 minus the old value; "
             f"the old 1 = new 5 mapping comes from the GM brief and is not confirmed in the CMMS): {shown}",
             f"worst-case incidents (normalised level 5): {len(worst)}" + (f" ({', '.join(sorted(worst))})" if worst and len(worst) <= 10 else ""),
             "raw severity values as logged, mixing both scales (do not use these as worst counts): "
             + ", ".join(f"logged {key}: {count}" for key, count in sorted(raw.items()))]
    return lines


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
        rises = re.findall(r"(\d{4}-\d{2}): [^\n]*?Month-over-month change from \d{4}-\d{2}: vibration [+-][\d.]+ mm/s \(\+([\d.]+)%\)",
                           str(source.get("text") or ""))
        rising = [(month, float(percent)) for month, percent in rises if float(percent) > 10]
        if rising:
            parts.append("months where mean vibration rose more than 10% on the month before: "
                         + ", ".join(f"{_month_name(month)} (+{percent:g}%)" for month, percent in rising)
                         + f"; the rise starts in {_month_name(rising[0][0])}")
        else:
            parts.append("no month where mean vibration rose more than 10% on the month before")
        lines.append("; ".join(parts) + ".")
    return lines


def _fahrenheit(lines: list[str]) -> list[str]:
    """Code-converted Fahrenheit values for the temperatures in the sensor facts (the data is stored in Celsius)."""
    out = []
    for line in lines:
        machine = re.match(r"Sensor months for (\S+):", line)
        values = re.findall(r"((?:mean|maximum) temperature) lowest ([\d.]+) C \(([^)]+)\), highest ([\d.]+) C \(([^)]+)\)", line)
        if not machine or not values:
            continue
        shown = "; ".join(f"{label} lowest {float(low) * 9 / 5 + 32:.1f} F ({low_month}), highest {float(high) * 9 / 5 + 32:.1f} F "
                          f"({high_month})" for label, low, low_month, high, high_month in values)
        out.append(f"Temperatures for {machine.group(1)} are stored in Celsius; converted by code to Fahrenheit: {shown}.")
    return out


def _month_name(month: str) -> str:
    return date.fromisoformat(month + "-01").strftime("%b %Y")


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
    if len(rows) <= 12:
        parts.append("parts listed: " + ", ".join(f"{row.get('Part No')} (for {row.get('For Machine')}, quantity {row.get('Qty')})"
                                                  for row in rows))
    empty = [str(row.get("Part No")) for row in rows if _number(row.get("Qty")) == 0]
    parts.append(f"{len(empty)} out of stock (quantity 0)" + (f" ({', '.join(empty)})" if empty else ""))
    if costs:
        parts.append(f"unit cost from {_money(min(costs))} to {_money(max(costs))} (the workbook states no currency; "
                     "SGD is assumed, not confirmed)")
    return "; ".join(parts) + ". Lead times are text in the workbook and are not summed."


_GRADE = re.compile(r"\bv?g\s?(\d{2,3})\b", re.I)


def lubricant_facts(plates: list[dict]) -> str | None:
    """Readable lubricant per machine from the nameplate OCR, grouped by ISO VG grade or brand."""
    from jm_rag.gaps import raw_reading

    readings: dict[str, str] = {}
    raw_text: dict[str, str] = {}
    for source in plates:
        tag = str(source.get("asset_tag") or "").upper()
        if source.get("source_type") == "processed_ocr_text":
            raw_text[tag] = raw_reading("lubricant", str(source.get("text") or "")) or ""
            continue
        value = record_of(source).get("lubricant")
        if tag and (value or tag not in readings):
            readings[tag] = str(value or "")
    for tag, value in raw_text.items():   # the structured field missed it, the raw OCR text has it next to the label
        if value and not readings.get(tag):
            readings[tag] = value
    if not readings:
        return None
    groups: dict[str, list[str]] = {}
    for tag, value in sorted(readings.items()):
        grade = _GRADE.search(value)
        if grade:
            key = f"ISO VG{grade.group(1)}"
        elif re.search(r"tonna", value, re.I):
            key = "Shell Tonna (brand oil)"
        elif value:
            key = "unreadable text"
        else:
            key = "no lubricant read"
        groups.setdefault(key, []).append(tag)
    shown = "; ".join(f"{key}: {', '.join(tags)}" for key, tags in sorted(groups.items()))
    return (f"Nameplate lubricant by machine (unverified OCR, grade read from the plate text): {shown}. "
            f"{len([k for k in groups if k.startswith(('ISO', 'Shell'))])} different readable lubricants.")


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
        if kind == "lubricant":
            line = lubricant_facts(records)
        elif kind == "work_order":
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
    if re.search(r"\bfahrenheit\b|°\s*f\b|\bdeg(?:rees)?\s*f\b", question, re.I):
        lines += _fahrenheit(lines)
    text = ("Facts computed by code from all matching records, not only the ones shown. "
            "Use these for counts, totals, minima, maxima and date ranges. " + " ".join(lines)
            + f" The data ends on {DATA_END:%d %b %Y}.")
    return {"title": TITLE, "text": text, "location": LOCATION, "source_type": "computed_facts"}
