"""Intent detection and TF-IDF retrieval over the loaded sources."""
from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from jm_rag.config import ASSET_PATTERN

SPARES_LIST_QUESTION = re.compile(r"\b(?:spares?|parts?)\s+(?:do|does)\s+(?:we|you)\b|\b(?:hold|holding|keep|kept|carry)\b.{0,20}\bfor\b", re.I)
from jm_rag.dates import (
    date_clarification, parse_date_window, parse_explicit_date, partial_month, partial_work_order_date,
)
from jm_rag.incidents import INCIDENT_TYPES, group_incident_events
from jm_rag.intents import is_history_table_request, is_work_order_table_request
from jm_rag.tags import DOCUMENT_WORDS, question_tags, question_word_machines, sensor_tags


SHIFT_WORDS = re.compile(r"\b(?:night|day)\s*shifts?\b|\bat night\b|\bduring the (?:night|day)\b|\bovernight\b|\bby day\b", re.I)
STRICT_SENSOR = re.compile(r"\b(?:sensors?|vibrat\w*|temperatures?|time.series|readings?|running off|runs? off|drift\w*)\b", re.I)
WO_TYPES = (("breakdown", "BREAK"), ("preventive", "PREV"), ("corrective", "CORR"))
FAMILY = {"document": "doc", "nameplate": "plate", "processed_nameplate": "plate", "processed_ocr_text": "plate",
          "tabular": "spares", "incident": "incident", "incident_ocr": "incident", "processed_incident": "incident",
          "work_order": "work_order", "sensor_summary": "sensor", "sensor_trend_monthly": "sensor",
          "processed_sensor_summary": "sensor", "processed_sensor_gaps": "sensor", "sensor_shift_monthly": "sensor"}


def _work_order_type(question: str) -> str | None:
    for word, prefix in WO_TYPES:
        if re.search(rf"\b{word}s?\b", question, re.I):
            return prefix
    return None


def _interleave(indexes: list[int], candidates: list[dict], wanted: set[str]) -> list[int]:
    """Round-robin the ranked results across the topics asked about, so one topic cannot fill every slot."""
    lanes: dict[str, list[int]] = {}
    for index in indexes:
        lanes.setdefault(FAMILY.get(candidates[index].get("source_type"), "other"), []).append(index)
    if len([lane for lane in lanes if lane in wanted]) < 2:
        return indexes
    merged, position = [], 0
    while any(position < len(lane) for lane in lanes.values()):
        merged += [lane[position] for lane in lanes.values() if position < len(lane)]
        position += 1
    return merged


def _matches_report(source: dict, key: str) -> bool:
    """Is this source the report ``key`` (IR-YYYY-N)? A CMMS incident matches by its ID and the year of its date."""
    if source.get("record_key") == key:
        return True
    when = source.get("incident_date")
    return (source.get("source_type") == "incident" and f"IR-{getattr(when, 'year', '')}-{source.get('incident_id')}" == key)


class Plan(SimpleNamespace):
    """What the question is about and which sources survive the tag, date and report filters."""


def plan_query(question: str, sources: list[dict]) -> Plan | None:
    """Intents plus the filtered candidate sources, before any ranking. None when retrieval must return nothing."""
    tags, unknown_tags = question_tags(question, sources)
    for source in sources:
        if not source.get("machine_record"):
            continue
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", question, re.I)
               for alias in source.get("asset_aliases", [])):
            if source.get("asset_tag"):
                tags.add(source["asset_tag"].upper())
    work_order_intent = bool(re.search(
        r"\b(?:work.orders?|service.records?|service.history|servicing|maintenance|repairs?|pm|preventive|corrective|"
        r"breakdowns?|wo\s*\d)\b",
        question, re.I,
    ))
    ambiguous_words: dict[str, set[str]] = {}
    if not tags and not DOCUMENT_WORDS.search(question):
        word_tags, ambiguous_words = question_word_machines(question, sources)
        tags |= word_tags
    incident_intent = bool(re.search(
        r"\b(?:incidents?|near.miss(?:es)?|severity|lost.days|injur(?:y|ies|ed)|hurt|accidents?)\b", question, re.I,
    ))
    combined_history_intent = work_order_intent and incident_intent and is_history_table_request(question)
    date_window = parse_date_window(question) if (work_order_intent or incident_intent) else None
    capability_intent = bool(re.search(
        r"\b(?:benefits?|advantages?|features?|capabilities?|what can (?:this )?(?:assistant|app) do|"
        r"what does (?:this )?(?:assistant|app) do|describe (?:this )?(?:assistant|app))\b",
        question, re.I,
    ))
    report_matches = re.findall(r"\bIR[-\s](20\d{2})[-\s](\d{3,6})\b", question, re.I)
    report_keys = {f"IR-{year}-{int(number)}" for year, number in report_matches}
    preferred_types = set()
    part_numbers = {str(s.get("title", "")).rsplit(" / ", 1)[-1].upper() for s in sources if s.get("source_type") == "tabular"}
    if re.search(r"\b(?:spares?|stock|part number|inventory|lead time|minimum quantity|reorder\w*|below min\w*|out of stock|"
                 r"running (?:out|low))\b|\border\b.{0,30}\b(?:urgent\w*|anything|soon|now)\b", question, re.I) or any(
            re.search(rf"(?<![\w-]){re.escape(part)}(?![\w-])", question, re.I) for part in part_numbers if part):
        preferred_types.add("tabular")
    # sensor words match by stem, so "vibrating", "vibrates" and "temperatures" count
    sensor_intent = bool(re.search(
        r"\b(?:sensors?|vibrat\w*|temperatures?|readings?|trend\w*|time.series|gaps?|running off|runs? off|"
        r"feels? off|drift\w*|abnormal|unusual)\b", question, re.I))
    sensor_trend_intent = bool(sensor_intent and re.search(
        r"\b(?:trend\w*|increas\w*|ris(?:e|es|ing)|decreas\w*|fall\w*|falling|chang\w*|month.over.month|"
        r"more|less|higher|lower|worse|climb\w*|drift\w*)\b",
        question, re.I,
    ))
    if sensor_intent and SHIFT_WORDS.search(question):
        preferred_types.add("sensor_shift_monthly")
    if sensor_intent:
        if sensor_trend_intent:
            preferred_types.add("sensor_trend_monthly")
        else:
            preferred_types.update({"sensor_summary", "processed_sensor_summary", "processed_sensor_gaps"})
        if not sensor_trend_intent and re.search(r"\b(?:audit|completeness|data quality|sensor csv)\b", question, re.I):
            preferred_types.add("processed_audit")
    if re.search(r"\b(?:incident|near.miss|severity|lost.days|injur(?:y|ies|ed)|hurt|accidents?)\b", question, re.I):
        preferred_types.update({"incident", "incident_ocr", "processed_incident"})
    if work_order_intent and partial_work_order_date(question):
        return None
    if work_order_intent and partial_month(question):
        return None   # a month with no year must be asked about
    if (work_order_intent or incident_intent) and date_clarification(question):
        return None  # an unreadable date must be asked about, not guessed (Phase 4b fix 1)
    exact_work_order_date = parse_explicit_date(question) if work_order_intent else None
    if work_order_intent:
        preferred_types.add("work_order")
    recent_work_orders = bool(work_order_intent and (
        is_work_order_table_request(question) or re.search(r"\b(?:recent|latest|last)\b", question, re.I)
    ))
    strict_sensor = bool(STRICT_SENSOR.search(question))
    lube_intent = bool(re.search(r"\b(?:lubricants?|lubricat\w*|lubes?|oils?|grease|greasing|viscosity|vg\s?\d+|tonna|iso\s+vg)\b",
                                 question, re.I))
    if lube_intent or DOCUMENT_WORDS.search(question):
        recent_work_orders = False   # "I am servicing CNC-02: which procedure, which oil" is not a work-order listing
    if not sensor_intent and (lube_intent or re.search(
            r"\b(?:manufacturer|model|serial|nameplate|capacity|electrical|power|weight)\b", question, re.I)):
        preferred_types.update({"nameplate", "processed_nameplate", "processed_ocr_text"})
    if re.search(r"\b(?:sop|procedure|permit|loto|lockout|confined.space|operator|lift(?:ing)?)\b", question, re.I):
        preferred_types.add("document")
    def source_tags(source: dict) -> set[str]:
        values = source.get("asset_tags")
        if values is None:
            values = [source["asset_tag"]] if source.get("asset_tag") else []
        return {str(value).upper() for value in values if value}

    spares_intent = "tabular" in preferred_types and bool(SPARES_LIST_QUESTION.search(question))
    # a spares row listed for "ALL" stays in a machine's spares answer, as an unresolved entry (it is never expanded)
    candidates = [source for source in sources
                  if not tags or not source_tags(source) or source_tags(source) & tags
                  or (spares_intent and source.get("source_type") == "tabular" and source_tags(source) == {"ALL"})]
    if unknown_tags and not tags:
        candidates = []  # a machine tag that matches no machine: abstain instead of returning other machines (fix 2)
    # a sensor question about a machine with no sensor data abstains (fix 5)
    with_data = sensor_tags(sources)
    sensorless_tags = sorted(tags - with_data) if (strict_sensor and with_data and tags) else []
    other_intent = work_order_intent or incident_intent or lube_intent
    if sensorless_tags and not (tags & with_data) and not other_intent:
        candidates = []
    if capability_intent:
        candidates = [source for source in candidates if source.get("source_type") == "app_capability"]

    if date_window:
        target_types = set()
        if work_order_intent:
            target_types.add("work_order")
        if incident_intent:
            target_types.update({"incident", "incident_ocr", "processed_incident"})
        filtered = []
        for source in candidates:
            source_type = source.get("source_type")
            if source_type not in target_types:
                continue
            raw_date = source.get("record_date") if source_type == "work_order" else source.get("incident_date")
            if raw_date is None:
                continue
            source_date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date)[:10])
            if date_window[0] <= source_date < date_window[1]:
                filtered.append(source)
        candidates = filtered

    wanted_type = _work_order_type(question) if work_order_intent else None
    if wanted_type:   # "breakdowns" narrows the work orders to that type
        candidates = [source for source in candidates if source.get("source_type") != "work_order"
                      or str((source.get("record") or {}).get("wo_type", "")).upper().startswith(wanted_type)]

    if report_keys:
        report_years = {key.rsplit("-", 1)[-1]: key.split("-")[1] for key in report_keys}
        exact_incidents = [source for source in candidates
                           if source.get("record_key") in report_keys
                           or (source.get("source_type") == "incident"
                               and str(source.get("incident_id", "")) in report_years
                               and str(getattr(source.get("incident_date"), "year", ""))
                               == report_years[str(source.get("incident_id"))])]
        candidates = exact_incidents  # no match at all means abstain, not "all incidents" (fix 4)
    found_reports = {key for key in report_keys if any(_matches_report(source, key) for source in candidates)}
    return Plan(tags=tags, candidates=candidates, work_order_intent=work_order_intent, incident_intent=incident_intent,
                combined_history_intent=combined_history_intent, capability_intent=capability_intent,
                sensor_intent=sensor_intent, sensor_trend_intent=sensor_trend_intent, preferred_types=preferred_types,
                recent_work_orders=recent_work_orders, date_window=date_window, report_keys=report_keys,
                lube_intent=lube_intent, ambiguous_words=ambiguous_words, unknown_tags=sorted(unknown_tags), sensorless_tags=sensorless_tags,
                sensor_tags=sorted(with_data), missing_reports=sorted(report_keys - found_reports),
                other_intent=other_intent)


def retrieve(question: str, sources: list[dict], limit: int = 5) -> list[dict]:
    if not sources:
        return []
    plan = plan_query(question, sources)
    if plan is None or not plan.candidates:
        return []
    tags, candidates, preferred_types = plan.tags, plan.candidates, plan.preferred_types
    work_order_intent, incident_intent = plan.work_order_intent, plan.incident_intent
    combined_history_intent, capability_intent = plan.combined_history_intent, plan.capability_intent
    sensor_trend_intent, recent_work_orders = plan.sensor_trend_intent, plan.recent_work_orders
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    try:
        matrix = vectorizer.fit_transform([source["title"] + " " + source["text"] for source in candidates])
        search_question = ASSET_PATTERN.sub(" ", question) if tags else question
        if re.search(r"\b(?:servic(?:e|ing)|maintenance|pm)\b", question, re.I):
            search_question += " work order maintenance service servicing preventive PM"
        if plan.sensor_intent:
            search_question += " sensor vibration temperature readings"
        if plan.lube_intent:
            search_question += " lubricant grease oil"
        if "tabular" in preferred_types:
            search_question += " spare part inventory stock quantity"
        if sensor_trend_intent:
            search_question += " monthly mean vibration RMS normalized temperature trend increase rise decrease change month-over-month"
        if incident_intent:
            search_question += " incident report safety incident history severity"
        query_vector = vectorizer.transform([search_question])
    except ValueError:
        return []
    scores = cosine_similarity(query_vector, matrix)[0]
    order = sorted(range(len(candidates)), key=lambda index: float(scores[index]), reverse=True)
    selected = [index for index in order if scores[index] > 0]
    if capability_intent:
        selected = [index for index in order if candidates[index].get("source_type") == "app_capability"]
    if tags:
        selected = [index for index in order if candidates[index].get("asset_tag") and scores[index] > 0]
        selected += [index for index in order if not candidates[index].get("asset_tag") and scores[index] > 0]
        if not selected and not search_question.strip():
            selected = order
    if preferred_types:
        preferred = [index for index in order if candidates[index].get("source_type") in preferred_types]
        relevant = [index for index in preferred if scores[index] > 0]
        if relevant:
            selected = _interleave(relevant, candidates, {FAMILY[t] for t in preferred_types if t in FAMILY})
        elif tags and not search_question.strip():
            selected = preferred or selected
    if combined_history_intent:
        order_indices = [index for index in order
                         if candidates[index].get("source_type") == "work_order" and scores[index] > 0]
        order_indices.sort(key=lambda index: str(candidates[index].get("record_date") or ""), reverse=True)
        scored_incidents = [index for index in order
                            if candidates[index].get("source_type") in INCIDENT_TYPES and scores[index] > 0]
        position = {id(candidates[index]): index for index in scored_incidents}
        event_groups = [[position[id(source)] for source in versions]
                        for versions in group_incident_events([candidates[index] for index in scored_incidents])]
        recent_incidents = sorted(
            event_groups,
            key=lambda group: max(str(candidates[index].get("incident_date") or "") for index in group),
            reverse=True,
        )[:10]
        incident_indices = [index for group in recent_incidents for index in group]
        selected = incident_indices + order_indices[:10]
    elif recent_work_orders and not incident_intent:
        work_orders = [index for index in selected if candidates[index].get("source_type") == "work_order"]
        work_orders.sort(key=lambda index: str(candidates[index].get("record_date") or ""), reverse=True)
        if work_orders:
            selected = work_orders
    return [{**candidates[index], "id": f"S{position + 1}", "score": round(float(scores[index]), 3)}
            for position, index in enumerate(selected[:limit])]

def matching_records(question: str, sources: list[dict]) -> dict:
    """All records that match the question's machine, date and topic filters, before ranking and the limit.

    Returns {} when the question is not about records, else the keys "tags", "window" and one list per topic
    ("work_order", "incident", "sensor", "spares"). The computed facts are worked out from these lists.
    """
    plan = plan_query(question, sources) if sources else None
    if plan is None:
        return {}
    by_type = lambda *types: [source for source in plan.candidates if source.get("source_type") in types]  # noqa: E731
    found = {"tags": plan.tags, "window": plan.date_window}
    if plan.work_order_intent:
        found["work_order"] = by_type("work_order")
    if plan.incident_intent:
        found["incident"] = by_type("incident", "incident_ocr", "processed_incident")
    if plan.sensor_intent:
        found["sensor"] = by_type("sensor_trend_monthly")
    if "tabular" in plan.preferred_types:
        found["spares"] = by_type("tabular")
    if plan.lube_intent and not plan.sensor_intent:
        found["lubricant"] = by_type("nameplate", "processed_ocr_text")
    return found if len(found) > 2 else {}
