"""Required values: the figures from the computed facts (and the SOP IDs) that answer the question.

The computed facts are written by code in a fixed format (``facts.py``). For each kind of question this module
picks the figures that answer it (a count, a total, IDs, a date, a caveat) out of that text. The pipeline then
checks that the model's answer states each one; if not, it retries once with the list, and if they are still
missing it appends a short cited "Key figures" line built from the same text. Every value here is copied from the
facts text, so the appended line always passes the number check.
"""
from __future__ import annotations

import re
from datetime import date

DATA_END_OPTIONS = ["30 Jun 2026", "30 June 2026", "2026-06-30", "June 30, 2026"]
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def norm(text: str) -> str:
    """Lower case, commas inside numbers dropped, runs of spaces folded."""
    return re.sub(r"\s+", " ", re.sub(r"(?<=\d),(?=\d)", "", str(text).lower()))


def stated(answer: str, options: list[str]) -> bool:
    """True when the answer states one of the options (a number must not be part of a longer number)."""
    haystack = norm(answer)
    for option in options:
        needle = norm(option)
        if re.fullmatch(r"[\d.]+", needle):
            if re.search(rf"(?<![\d.]){re.escape(needle)}(?![\d]|\.\d)", haystack):
                return True
        elif needle and needle in haystack:
            return True
    return False


def _date_options(iso: str) -> list[str]:
    day = date.fromisoformat(iso)
    month = day.strftime("%b")
    return [iso, f"{day.day} {month} {day.year}", f"{day.day} {day.strftime('%B')} {day.year}", f"{month} {day.day}",
            f"{day.strftime('%B')} {day.day}", f"{day.day} {month}"]


def _month_options(label: str) -> list[str]:
    month, year = label.split()
    number = _MONTHS.index(month[:3].lower()) + 1
    full = date(int(year), number, 1).strftime("%B")
    return [label, f"{full} {year}", f"{year}-{number:02d}", full]


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?", text)


def _item(label: str, options: list[str], source_id: str, caveat: bool = False) -> dict:
    return {"label": label, "options": [option for option in options if option], "source": source_id, "caveat": caveat}


Q_OPEN = re.compile(r"\b(?:open|still|outstanding|not closed|awaiting|pending)\b", re.I)
Q_COUNT = re.compile(r"\b(?:how many|number of|count|total)\b", re.I)
Q_COST = re.compile(r"\b(?:spend|spent|cost|costs|how much)\b", re.I)
Q_EXPENSIVE = re.compile(r"\b(?:most expensive|costliest|highest cost|biggest cost)\b", re.I)
Q_PER_TYPE = re.compile(r"\b(?:per|by|each)\s+type\b", re.I)
Q_LIST = re.compile(r"\b(?:which|list|what)\b", re.I)
Q_PER_YEAR = re.compile(r"\b(?:per|each|by)\s+year\b|\bannual\w*\b|\byearly\b", re.I)
Q_MOST = re.compile(r"\bmost\b", re.I)
Q_WORST = re.compile(r"\b(?:worst|most severe)\b", re.I)
Q_LEVEL = re.compile(r"\bseverity\s*(?:level\s*)?(\d)\b", re.I)
Q_NEAR_LOST = re.compile(r"near[\s-]?miss.*\blost\b|\blost\b.*near[\s-]?miss", re.I)
Q_AUDIT = re.compile(r"\baudit\w*\b", re.I)
Q_FORM = re.compile(r"\b(?:form|forms|scanned)\b", re.I)
Q_RECENT = re.compile(r"\b(?:most recent|latest|recent|recently|last incident)\b", re.I)
Q_BELOW = re.compile(r"\b(?:below|minimum|min stock|order|reorder\w*|urgent\w*|running low|short)\b", re.I)
Q_EMPTY = re.compile(r"\bout of stock\b|\bno stock\b|\bzero stock\b|\bnone left\b", re.I)
Q_SPARES_LIST = re.compile(r"\b(?:hold|have|keep|carry)\b.{0,25}\bfor\b|\bspares?\s+(?:do|does)\b", re.I)
Q_RISE = re.compile(r"\b(?:running off|runs off|off|drift\w*|trend\w*|ris(?:e|es|ing)|increas\w*|more|chang\w*|started)\b", re.I)
Q_DATA_END = re.compile(r"\b(?:still|open|recent\w*|currently|now|latest|today|so far)\b", re.I)
Q_ALL_MACHINES = re.compile(r"\b(?:all|every|each)\s+(?:the\s+)?machines?\b", re.I)
Q_FAHRENHEIT = re.compile(r"\bfahrenheit\b|°\s*f\b|\bdeg(?:rees)?\s*f\b", re.I)


def required_from_facts(question: str, facts: dict | None) -> list[dict]:
    """Required values for the question, read out of the computed facts source (which must carry an id)."""
    if not facts or not facts.get("id"):
        return []
    text, sid, q = str(facts.get("text") or ""), facts["id"], question
    found: list[dict] = []

    def grab(pattern: str):
        return re.search(pattern, text, re.I | re.S)

    # work orders
    if Q_OPEN.search(q) and (m := grab(r"not closed \(open or awaiting parts\): (\d+)")):
        found.append(_item("work orders not closed", [m.group(1)], sid))
        if Q_LIST.search(q) and (ids := grab(r"not-closed work order IDs: ([\d, ]+)")):
            found += [_item(f"work order {number}", [number], sid) for number in _numbers(ids.group(1))]
    elif Q_COUNT.search(q) and (m := grab(r"Work orders \([^)]*\): (\d+) in total")):
        found.append(_item("work orders", [m.group(1)], sid))
    elif Q_LIST.search(q) and not (Q_EXPENSIVE.search(q) or Q_COST.search(q)) and (ids := grab(r"; work order IDs: ([\d, ]+)")):
        found += [_item(f"work order {number}", [number], sid) for number in _numbers(ids.group(1))]
    if Q_COST.search(q) and not Q_EXPENSIVE.search(q) and (m := grab(r"total cost ([\d,]+\.\d\d) SGD")):
        found.append(_item("total work-order cost (SGD)", [m.group(1)], sid))
    if Q_EXPENSIVE.search(q) and (m := grab(r"most expensive: work order (\d+) \(([\d,.]+) SGD")):
        found += [_item("most expensive work order", [m.group(1)], sid), _item("its cost (SGD)", [m.group(2)], sid)]
    if Q_PER_TYPE.search(q) and (m := grab(r"by type: ([^;]+)")):
        found += [_item(f"work orders of type {kind}", [count], sid) for kind, count in re.findall(r"([A-Z][A-Z ]+?) (\d+)", m.group(1))]

    # incidents
    worst = Q_WORST.search(q)
    level = Q_LEVEL.search(q)
    if Q_COUNT.search(q) and not (worst or level or Q_PER_YEAR.search(q) or Q_NEAR_LOST.search(q) or Q_AUDIT.search(q)
                                  or Q_FORM.search(q)) and (m := grab(r"Incidents \([^)]*\): (\d+) unique incidents")):
        found.append(_item("incidents", [m.group(1)], sid))
    if Q_PER_YEAR.search(q) and (m := grab(r"Incidents[^;]*;[^;]*; by year: ([^;]+)")):
        found += [_item(f"incidents in {year}", [count], sid) for year, count in re.findall(r"(20\d\d) (\d+)", m.group(1))]
    if Q_MOST.search(q) and re.search(r"\bincidents?\b", q, re.I) and (m := grab(r"most incidents: (\S+) with (\d+)")):
        found += [_item("machine with the most incidents", [m.group(1)], sid), _item("its incident count", [m.group(2)], sid)]
    if worst and (m := grab(r"worst-case incidents \(normalised level 5\): (\d+)(?: \(([^)]+)\))?")):
        found.append(_item("worst-case incidents (5 = worst on one scale)", [m.group(1)], sid))
        if m.group(2):
            found += [_item(f"worst-case incident {number}", [number], sid) for number in _numbers(m.group(2))]
    if (worst or level) and grab(r"is not confirmed in the CMMS"):
        found.append(_item("the old-to-new scale mapping is not confirmed",
                           ["not confirmed", "unconfirmed", "not yet confirmed"], sid, caveat=True))
    if worst and (m := grab(r"logged 5: (\d+)")):
        found.append(_item("incidents logged as 5, mixing both scales", [m.group(1)], sid))
    if level:
        n = level.group(1)
        if m := grab(rf"level {n}(?: \(([a-z ]+)\))?: (\d+)"):
            found.append(_item(f"incidents at level {n} on the one-scale view (5 = worst)", [m.group(2)], sid))
            if m.group(1):
                found.append(_item(f"level {n} meaning", [m.group(1)], sid))
        if m := grab(rf"logged {n}: (\d+)"):
            found.append(_item(f"incidents logged as {n}, mixing both scales", [m.group(1)], sid))
        found.append(_item("severity is on two scales (before 1 Jul 2025 1 is worst, from then 5 is worst)", ["scale"], sid, caveat=True))
    if Q_NEAR_LOST.search(q) and (m := grab(r"recorded as a near miss but with lost days: \d+ \(([^)]+)\)")):
        found += [_item(f"near miss with lost days, incident {number}", [number], sid) for number in _numbers(m.group(1))]
    if Q_AUDIT.search(q) and (m := grab(r"found during audit (\d+)")):
        found.append(_item("incidents found during an audit", [m.group(1)], sid))
    if Q_FORM.search(q) and (m := grab(r"with a scanned incident form \(OCR record\): (\d+)")):
        found.append(_item("incidents with a scanned form", [m.group(1)], sid))
    if Q_RECENT.search(q) and re.search(r"\bincidents?\b", q, re.I) and (
            m := grab(r"Incidents \([^)]*\): [^;]*; dated \d{4}-\d{2}-\d{2} to (\d{4}-\d{2}-\d{2})")):
        found.append(_item("date of the latest incident", _date_options(m.group(1)), sid))

    # spares
    if Q_BELOW.search(q) and (m := grab(r"\d+ below minimum quantity \(([^)]+)\)")):
        found += [_item(f"below minimum: {part.strip()}", [part.strip()], sid) for part in m.group(1).split(",")]
    if Q_EMPTY.search(q) and (m := grab(r"\d+ out of stock \(quantity 0\) \(([^)]+)\)")):
        found += [_item(f"out of stock: {part.strip()}", [part.strip()], sid) for part in m.group(1).split(",")]
    if Q_COST.search(q) and grab(r"SGD is assumed, not confirmed"):
        found.append(_item("the workbook states no currency; SGD is assumed", ["SGD is assumed", "assumed", "currency"], sid, caveat=True))
    if Q_SPARES_LIST.search(q) and (m := grab(r"parts listed: (.+?)\.(?: |$)")):
        found += [_item(f"part {part}", [part], sid) for part in re.findall(r"([A-Z][A-Z0-9.]+(?:-[A-Z0-9.]+)+) \(for", m.group(1))]

    # sensors
    if Q_RISE.search(q) and (m := grab(r"the rise starts in (\w{3} \d{4})")):
        found.append(_item("month the vibration rise starts", _month_options(m.group(1)), sid))
    if Q_FAHRENHEIT.search(q) and grab(r"stored in Celsius"):
        found.append(_item("the readings are stored in Celsius", ["Celsius", "°C"], sid, caveat=True))
        if m := grab(r"converted by code to Fahrenheit: (.+?)\.(?:\s|$)"):
            found += [_item(f"{label} (F)", [value], sid) for label, value in
                      re.findall(r"((?:mean|maximum) temperature (?:lowest|highest)) ([\d.]+) F", m.group(1))]

    # lubricants
    grade = re.search(r"\bvg\s?(\d{2,3})\b", q, re.I)
    if grade and (m := grab(rf"ISO VG{grade.group(1)}: ([^;.]+)")):
        found += [_item(f"uses ISO VG{grade.group(1)}: {tag.strip()}", [tag.strip()], sid) for tag in m.group(1).split(",")]
    if re.search(r"\btonna\b", q, re.I) and (m := grab(r"Shell Tonna \(brand oil\): ([^;.]+)")):
        found += [_item(f"uses Shell Tonna: {tag.strip()}", [tag.strip()], sid) for tag in m.group(1).split(",")]
    if Q_ALL_MACHINES.search(q) and (m := grab(r"Nameplate lubricant by machine[^:]*: (.+?)\. \d+ different")):
        found += [_item(f"lubricant {kind}", [kind.replace("ISO ", "")], sid)
                  for kind in re.findall(r"(ISO VG\d+|Shell Tonna)", m.group(1))]

    if Q_DATA_END.search(q) and grab(r"The data ends on 30 Jun 2026"):
        found.append(_item("the data ends on 30 Jun 2026", DATA_END_OPTIONS, sid, caveat=True))
    unique, seen = [], set()
    for item in found:
        key = (item["label"], tuple(item["options"]))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def required_sop_ids(answer: str, sources: list[dict]) -> list[dict]:
    """An SOP cited in the answer must be named, so the reader can find it."""
    cited = set(re.findall(r"\[(S\d+)\]", answer or ""))
    found = []
    for source in sources:
        title = str(source.get("title") or "")
        if source.get("source_type") == "document" and source.get("id") in cited and title.upper().startswith("SOP-"):
            sop = re.sub(r"\.(txt|md)$", "", title, flags=re.I)
            short = sop.split("-")[1] if sop.count("-") >= 2 else sop
            found.append(_item(f"SOP {sop}", [sop, short], source["id"]))
    return found


def missing(answer: str, required: list[dict]) -> list[dict]:
    return [item for item in required if not stated(answer, item["options"])]


def key_figures_line(items: list[dict]) -> str:
    """A short cited line built from the facts text: 'Key figures (computed by code): label: value [S#]; ...'."""
    parts = [f"{item['label']} [{item['source']}]" if item.get("caveat") else
             f"{item['label']}: {item['options'][0]} [{item['source']}]" for item in items]
    return "Key figures (computed by code): " + "; ".join(parts) + "."
