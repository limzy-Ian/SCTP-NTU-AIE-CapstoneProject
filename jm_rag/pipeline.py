"""The request pipeline: one function, one response dict (plan sections 5.1 and 5.2).

input guard -> clarify checks -> retrieve -> deterministic paths (tables, no evidence) or model answer ->
post-check, one retry, deterministic template -> mandatory notes and conflicts -> outcome -> output guard.
The model only phrases an answer from retrieved evidence. Code decides what is refused, which caveats are
mandatory and whether a draft is acceptable. Every model call is recorded in ``usage``, retries included.
"""
from __future__ import annotations

import calendar
import os
import re
import time

from jm_rag import conflicts as conflict_rules
from jm_rag import observability, validator
from jm_rag.dates import (
    date_clarification, partial_work_order_date, resolve_partial_work_order_date, resolve_relative_periods,
)
from jm_rag import gaps
from jm_rag.drafting import model_answer
from jm_rag.facts import facts_source
from jm_rag.followup import resolve_followup
from jm_rag.guardrails import input_guard, names, output_guard
from jm_rag.guardrails.sanitize import sanitize_sources, sanitize_text
from jm_rag.intents import is_aggregate_question, is_history_table_request, is_work_order_table_request
from jm_rag.notes import mandatory_notes
from jm_rag.outcome import decide_outcome
from jm_rag.retrieval import plan_query, retrieve
from jm_rag.tables import format_combined_history_table, format_incident_table, format_work_order_table
from jm_rag.tags import DOCUMENT_WORDS, machine_tags

LUBE_WORDS = re.compile(r"\b(?:oils?|lubricants?|lubes?|lubrication|grease)\b", re.I)



def failed_sources(warnings: list[str]) -> list[str]:
    """Labels of sources that could not be checked, read from the loader warnings."""
    failed: list[str] = []
    for warning in warnings:
        if warning.startswith("MySQL connection or review setup failed"):
            label = "MySQL (all tables)"
        elif (match := re.match(r"MySQL source (.+?) unavailable", warning)):
            label = f"MySQL {match.group(1)}"
        elif warning.startswith("Tabular spares unavailable"):
            label = "the spares workbook"
        else:
            continue
        if label not in failed:
            failed.append(label)
    return failed


def ambiguous_machines(question: str, sources: list[dict]) -> tuple[str, list[str]] | None:
    """(alias, tags) when a machine alias in the question maps to several machines and no tag is given."""
    aliases: dict[str, set[str]] = {}
    tags = set()
    for source in sources:
        if source.get("machine_record") and source.get("asset_tag"):
            tags.add(str(source["asset_tag"]).upper())
            for alias in source.get("asset_aliases", []):
                aliases.setdefault(str(alias).casefold(), set()).add(str(source["asset_tag"]).upper())
    if any(re.search(rf"(?<!\w){re.escape(tag)}(?!\w)", question, re.I) for tag in tags):
        return None
    for alias, owners in sorted(aliases.items()):
        if len(owners) > 1 and re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", question, re.I):
            return alias, sorted(owners)
    return None


def ambiguous_word(question: str, sources: list[dict]) -> tuple[str, list[str]] | None:
    """("lathe", tags) for "the lathe" when that word names several machines and nothing else picks one."""
    plan = plan_query(question, sources) if sources else None
    if plan is None or plan.tags:
        return None
    for word, owners in sorted(plan.ambiguous_words.items()):
        # "the lathe?" or "the crane is" names a machine; "the crane sling" uses the word to describe something else
        if re.search(rf"\bthe\s+{re.escape(word)}(?!s)\b(?=\s*(?:[?.!,;:]|$|{MACHINE_FOLLOWERS}\b))", question, re.I):
            return word, sorted(owners)
    return None


MACHINE_FOLLOWERS = (r"(?:is|was|are|has|have|had|does|did|do|on|in|at|for|with|and|or|now|today|running|doing|"
                     r"working|been|status|condition|history)")


def _gap_notes(question: str, sources: list[dict], all_sources: list[dict]) -> tuple[list[str], bool]:
    """Notes for what the data cannot give (unread or implausible plate fields, an SOP topic with no SOP, identity)."""
    plan = plan_query(question, all_sources) if all_sources else None
    tags = set(plan.tags) if plan else set()
    loads = set(conflict_rules._sop_rated_loads(sources))
    notes, abstain = gaps.plate_field_gaps(question, sources, tags, loads, all_sources)
    topic = gaps.sop_topic_gap(question, all_sources) or gaps.shift_gap(question, sources)
    if topic:
        notes.append(topic)
        abstain = True
    identity = gaps.identity_gap(question, all_sources)
    if identity:
        notes.append(identity[0])
        if identity[1] is not None and all(s.get("source_type") != "employee_data_quality" for s in sources):
            sources.append({**identity[1], "id": f"S{len(sources) + 1}"})
        abstain = True
    return notes, abstain


def _not_found_statements(question: str, all_sources: list[dict]) -> list[str]:
    """Things the question names that the data does not hold: an unknown machine, a missing report, no sensor data."""
    plan = plan_query(question, all_sources) if all_sources else None
    if plan is None:
        return []
    found = []
    if plan.unknown_tags:
        found.append(f"I could not find a machine with the ID {', '.join(plan.unknown_tags)}. "
                     f"Known machines: {', '.join(machine_tags(all_sources))}.")
    if plan.missing_reports:
        found.append(f"I could not find report {', '.join(plan.missing_reports)} in the CMMS incidents, "
                     "OCR staging or processed OCR.")
    if plan.sensorless_tags:
        found.append(f"I have no sensor data for {', '.join(plan.sensorless_tags)}. "
                     f"Sensor readings exist only for {', '.join(plan.sensor_tags)}.")
    return found


def _no_evidence_text(question: str, table_request: bool, combined: bool, failed: list[str]) -> str:
    if failed:
        return (f"I could not check {', '.join(failed)}, so I cannot say whether matching records exist. "
                "Please try again once the source is available.")
    if combined:
        return "I couldn't find matching incident or service records for the requested period in MySQL."
    if table_request and is_work_order_table_request(question):
        return "I couldn't find work orders matching the requested machine and date range in MySQL `work_orders`."
    if table_request:
        return "I couldn't find incident records matching the requested date range in the available sources."
    return "I could not find evidence to answer that question. Specify an asset tag or SOP topic."


def _finish(started, usage, trace, errors, *, answer, outcome, flags, sources=(), notes=(), refusal_class=None):
    result = output_guard.check(answer)
    if not result["ok"]:
        trace.append({"step": "output_guard", "leak": result["reason"]})
        answer, outcome, refusal_class, sources, notes = result["answer"], "refuse", "OUTPUT_GUARD", [], []
    elif result["names_unloaded"]:
        trace.append({"step": "output_guard", "flag": names.NAMES_UNLOADED_FLAG})
    cited = [identifier for identifier in validator.cited_ids(answer)
             if identifier in {source.get("id") for source in sources}]
    trace.append({"step": "done", "outcome": outcome, "ms": int((time.perf_counter() - started) * 1000)})
    return {"answer": answer, "outcome": outcome, "refusal_class": refusal_class, "sources": list(sources),
            "cited_ids": cited, "notes": list(notes), "flags": dict(flags), "usage": usage, "trace": trace,
            "errors": errors}


def answer_question(question, history, corpus, client, *, model=None, max_tokens=700) -> dict:
    """Answer one question. ``corpus`` is (sources, warnings) from load_sources(); ``client`` may be None."""
    started = time.perf_counter()
    usage, trace, errors = observability.new_usage(), [], []
    all_sources, warnings = corpus if isinstance(corpus, tuple) else (corpus, [])
    model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    history = [{"role": item["role"], "content": sanitize_text(item["content"])} for item in (history or [])]
    guard = input_guard.check(question, has_history=bool(history))
    flags = {"inference_request": False, "needs_future_date": False, "asks_missing_document": False,
             "asks_schedule": False, **guard["flags"]}
    trace.append({"step": "input_guard", "verdict": guard["verdict"], "class": guard["class"]})
    if not names.terms_loaded():
        trace.append({"step": "names", "flag": names.NAMES_UNLOADED_FLAG})
    if guard["verdict"] == "refuse":
        return _finish(started, usage, trace, errors, answer=guard["message"], outcome="refuse", flags=flags,
                       refusal_class=guard["class"])
    failed = failed_sources(warnings)
    if failed:
        errors += [f"could not check {label}" for label in failed]

    partial = partial_work_order_date(question)
    if partial:
        day, month, raw = partial
        text = (f"I read `{raw}` as {day} {calendar.month_name[month]}, but the year is missing. "
                "Which year should I search? I haven't queried the work orders yet.")
        return _finish(started, usage, trace, errors, answer=text, outcome="clarify", flags=flags)
    unclear_date = date_clarification(question)
    if unclear_date:
        return _finish(started, usage, trace, errors, answer=unclear_date, outcome="clarify", flags=flags)
    ambiguous = ambiguous_machines(question, all_sources) or ambiguous_word(question, all_sources)
    if ambiguous:
        alias, tags = ambiguous
        text = (f"`{alias}` matches more than one machine ({', '.join(tags)}). Which one do you mean? "
                f"Give the machine ID, for example {tags[0]}.")
        return _finish(started, usage, trace, errors, answer=text, outcome="clarify", flags=flags)

    previous = next((item["content"] for item in reversed(history) if item["role"] == "user"), "")
    retrieval_question = question
    if re.fullmatch(r"20\d{2}", question.strip()):
        if partial_work_order_date(previous):
            retrieval_question = resolve_partial_work_order_date(previous, int(question.strip()))
    elif resolve_followup(question, previous):
        retrieval_question = resolve_followup(question, previous)
    elif not any(character.isdigit() for character in question):
        retrieval_question = (previous + " " + question).strip()
    retrieval_question = resolve_relative_periods(retrieval_question)   # "last year" is 2025 (A14)
    aggregate = is_aggregate_question(retrieval_question)
    # "I am servicing CNC-02, which procedure applies and what oil" is not a request for a service-history table
    other_topic = bool(DOCUMENT_WORDS.search(question) or LUBE_WORDS.search(question))
    table_request = is_history_table_request(retrieval_question) and not aggregate and not other_topic
    combined = bool(re.search(r"\b(?:incidents?|near.miss(?:es)?)\b", retrieval_question, re.I)
                    and re.search(r"\b(?:service|servicing|work.order|maintenance)\b", retrieval_question, re.I)
                    and not aggregate and not other_topic)
    sources = sanitize_sources(retrieve(retrieval_question, all_sources,
                                        limit=50 if combined else 10 if table_request else 5))
    trace.append({"step": "retrieve", "sources": len(sources), "table_request": table_request})

    if table_request:
        # a history table needs rows of the right kind; other sources (an SOP chunk, a capability guide) are not an answer
        row_types = ({"work_order"} if is_work_order_table_request(retrieval_question) and not combined else
                     {"incident", "incident_ocr", "processed_incident"} if not combined else
                     {"work_order", "incident", "incident_ocr", "processed_incident"})
        if not any(source.get("source_type") in row_types for source in sources):
            sources = []

    not_found = _not_found_statements(retrieval_question, all_sources)
    note = None
    if not sources:
        body = " ".join(not_found) if (not_found and not failed) else _no_evidence_text(
            retrieval_question, table_request, combined, failed)
        path = "not_found" if (not_found and not failed) else "no_evidence"
    elif combined:
        body, path = format_combined_history_table(sources), "table"
    elif table_request and is_work_order_table_request(retrieval_question):
        body, path = format_work_order_table(sources), "table"
    elif table_request:
        body, path = format_incident_table(sources), "table"
    else:
        extra = conflict_rules.related_sources(retrieval_question, sources, all_sources)
        computed = facts_source(retrieval_question, all_sources)
        if computed:
            extra.append(computed)
        extra = sanitize_sources(extra)
        sources = sources + [{**source, "id": f"S{len(sources) + position + 1}"} for position, source in enumerate(extra)]
        trace.append({"step": "facts", "computed": bool(computed)})
        body, note = model_answer(question, retrieval_question, history, sources, sanitize_text(str(warnings)), client,
                                  model,
                                   usage, trace, errors, max_tokens, flags=flags)
        path = "template" if note else "model"
    trace.append({"step": "path", "path": path})

    found = conflict_rules.find_conflicts(sources, question, all_sources)
    notes, gap = _gap_notes(retrieval_question, sources, all_sources)
    notes = mandatory_notes(flags, question, sources) + notes
    notes += [item["text"] for item in found]
    if note:
        notes.append(note)
    if sources:
        notes += not_found  # something asked about was not found, though other evidence was
    if failed and sources:
        notes.append(f"I could not check {', '.join(failed)}; this answer uses only the sources that were available.")
    outcome = decide_outcome(flags=flags, has_evidence=bool(sources), failed_sources=failed, conflicts=found, gap=gap)
    trace.append({"step": "outcome", "outcome": outcome, "conflicts": len(found)})
    text = body + ("\n\nNotes:\n" + "\n".join(f"- {item}" for item in notes) if notes else "")
    return _finish(started, usage, trace, errors, answer=text, outcome=outcome, flags=flags, sources=sources,
                   notes=notes)
