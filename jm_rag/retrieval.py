"""Intent detection and TF-IDF retrieval over the loaded sources."""
from __future__ import annotations

import re
from datetime import date

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from jm_rag.config import ASSET_PATTERN
from jm_rag.dates import parse_date_window, parse_explicit_date, partial_work_order_date
from jm_rag.intents import is_history_table_request, is_work_order_table_request


def retrieve(question: str, sources: list[dict], limit: int = 5) -> list[dict]:
    if not sources:
        return []
    tags = {match.upper() for match in ASSET_PATTERN.findall(question)}
    for source in sources:
        if not source.get("machine_record"):
            continue
        if any(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", question, re.I)
               for alias in source.get("asset_aliases", [])):
            if source.get("asset_tag"):
                tags.add(source["asset_tag"].upper())
    work_order_intent = bool(re.search(
        r"\b(?:work.orders?|service.records?|servicing|maintenance|repairs?|pm|preventive|corrective|wo\s*\d)\b",
        question, re.I,
    ))
    incident_intent = bool(re.search(
        r"\b(?:incidents?|near.miss(?:es)?|severity|lost.days|injur(?:y|ies))\b", question, re.I,
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
    if re.search(r"\b(?:spares?|stock|part number|inventory|lead time|minimum quantity)\b", question, re.I):
        preferred_types.add("tabular")
    sensor_intent = bool(re.search(r"\b(?:sensor|vibration|temperature|readings?|trend|time.series|gaps?)\b", question, re.I))
    sensor_trend_intent = bool(sensor_intent and re.search(
        r"\b(?:trend|increase|increasing|rise|rising|decrease|decreasing|fall|falling|change|month.over.month)\b",
        question, re.I,
    ))
    if sensor_intent:
        if sensor_trend_intent:
            preferred_types.add("sensor_trend_monthly")
        else:
            preferred_types.update({"sensor_summary", "processed_sensor_summary", "processed_sensor_gaps"})
        if not sensor_trend_intent and re.search(r"\b(?:audit|completeness|data quality|sensor csv)\b", question, re.I):
            preferred_types.add("processed_audit")
    if re.search(r"\b(?:incident|near.miss|severity|lost.days|injur(?:y|ies))\b", question, re.I):
        preferred_types.update({"incident", "incident_ocr", "processed_incident"})
    if work_order_intent and partial_work_order_date(question):
        return []
    exact_work_order_date = parse_explicit_date(question) if work_order_intent else None
    if work_order_intent:
        preferred_types.add("work_order")
    recent_work_orders = bool(work_order_intent and (
        is_work_order_table_request(question) or re.search(r"\b(?:recent|latest|last)\b", question, re.I)
    ))
    if not sensor_intent and re.search(r"\b(?:manufacturer|model|serial|nameplate|lubricant|grease|capacity|electrical|power|weight)\b", question, re.I):
        preferred_types.update({"nameplate", "processed_nameplate", "processed_ocr_text"})
    if re.search(r"\b(?:sop|procedure|permit|loto|lockout|confined.space|operator|lift(?:ing)?)\b", question, re.I):
        preferred_types.add("document")
    def source_tags(source: dict) -> set[str]:
        values = source.get("asset_tags")
        if values is None:
            values = [source["asset_tag"]] if source.get("asset_tag") else []
        return {str(value).upper() for value in values if value}

    candidates = [source for source in sources
                  if not tags or not source_tags(source) or source_tags(source) & tags]
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

    if report_keys:
        report_years = {key.rsplit("-", 1)[-1]: key.split("-")[1] for key in report_keys}
        exact_incidents = [source for source in candidates
                           if source.get("record_key") in report_keys
                           or (source.get("source_type") == "incident"
                               and str(source.get("incident_id", "")) in report_years
                               and str(getattr(source.get("incident_date"), "year", ""))
                               == report_years[str(source.get("incident_id"))])]
        if exact_incidents:
            candidates = exact_incidents
    if not candidates:
        return []
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english")
    try:
        matrix = vectorizer.fit_transform([source["title"] + " " + source["text"] for source in candidates])
        search_question = ASSET_PATTERN.sub(" ", question) if tags else question
        if re.search(r"\b(?:servic(?:e|ing)|maintenance|pm)\b", question, re.I):
            search_question += " work order maintenance service servicing preventive PM"
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
            selected = relevant
        elif tags and not search_question.strip():
            selected = preferred or selected
    if combined_history_intent:
        order_indices = [index for index in order
                         if candidates[index].get("source_type") == "work_order" and scores[index] > 0]
        order_indices.sort(key=lambda index: str(candidates[index].get("record_date") or ""), reverse=True)
        incident_groups: dict[str, list[int]] = {}
        for index in order:
            source = candidates[index]
            if source.get("source_type") not in {"incident", "incident_ocr", "processed_incident"} or scores[index] <= 0:
                continue
            event_key = source.get("record_key") or source.get("incident_id")
            event_id = str(event_key).rsplit("-", 1)[-1] if event_key else source["title"]
            incident_groups.setdefault(event_id, []).append(index)
        recent_incidents = sorted(
            incident_groups.items(),
            key=lambda item: max(str(candidates[index].get("incident_date") or "") for index in item[1]),
            reverse=True,
        )[:10]
        incident_indices = [index for _, group in recent_incidents for index in group]
        selected = incident_indices + order_indices[:10]
    elif recent_work_orders and not incident_intent:
        work_orders = [index for index in selected if candidates[index].get("source_type") == "work_order"]
        work_orders.sort(key=lambda index: str(candidates[index].get("record_date") or ""), reverse=True)
        if work_orders:
            selected = work_orders
    return [{**candidates[index], "id": f"S{position + 1}", "score": round(float(scores[index]), 3)}
            for position, index in enumerate(selected[:limit])]
