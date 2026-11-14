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
from jm_rag.dates import partial_work_order_date, resolve_partial_work_order_date
from jm_rag.guardrails import input_guard, names, output_guard
from jm_rag.guardrails.sanitize import sanitize_sources, sanitize_text
from jm_rag.intents import is_history_table_request, is_work_order_table_request
from jm_rag.notes import mandatory_notes
from jm_rag.outcome import decide_outcome
from jm_rag.prompt import load_system_prompt, serialize_evidence
from jm_rag.retrieval import retrieve
from jm_rag.tables import format_combined_history_table, format_incident_table, format_work_order_table
from jm_rag.template import build_template_answer

NOT_CONFIGURED_NOTE = "The AI endpoint is not configured, so this lists the retrieved evidence directly."
ENDPOINT_DOWN_NOTE = "The AI endpoint is unavailable, so this lists the retrieved evidence directly."
UNVERIFIED_DRAFT_NOTE = ("The AI draft could not be verified against the evidence after one retry, so this lists "
                         "the retrieved evidence directly.")


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


def _call_model(client, model, messages, step, usage, trace, max_tokens):
    started = time.perf_counter()
    try:
        response = client.chat.completions.create(model=model, temperature=0, max_tokens=max_tokens, messages=messages)
    except Exception as error:  # noqa: BLE001 - any client failure means "model unavailable"
        observability.record_call(usage, step, model, None, (time.perf_counter() - started) * 1000,
                                  error=type(error).__name__)
        trace.append({"step": step, "error": type(error).__name__})
        raise
    observability.record_call(usage, step, model, getattr(response, "usage", None),
                              (time.perf_counter() - started) * 1000)
    return response.choices[0].message.content or ""


def _problems(draft: str, sources: list[dict], question: str) -> list[str]:
    found = validator.post_check(draft, sources, question)
    if validator.unsafe_language(draft):
        found.append("The answer asks for or describes a safety bypass or private data. Remove it.")
    return [sanitize_text(item) for item in found]


def _model_answer(question, history, sources, warnings, client, model, usage, trace, errors, max_tokens):
    """Return (answer, note). A note is set when the template was used instead of the model."""
    if client is None:
        return build_template_answer(sources, question), NOT_CONFIGURED_NOTE
    evidence = serialize_evidence(sources)
    messages = ([{"role": "system", "content": load_system_prompt()}] + history
                + [{"role": "user", "content": f"Question: {question}\nSource availability warnings: {warnings}\n"
                                               f"Retrieved evidence:\n{evidence}"}])
    try:
        draft = _call_model(client, model, messages, "answer", usage, trace, max_tokens)
    except Exception as error:  # noqa: BLE001
        errors.append(f"model unavailable ({type(error).__name__})")
        return build_template_answer(sources, question), ENDPOINT_DOWN_NOTE
    problems = _problems(draft, sources, question)
    trace.append({"step": "post_check", "attempt": 1, "problems": len(problems)})
    if not problems:
        return draft, None
    retry_messages = messages + [
        {"role": "assistant", "content": sanitize_text(draft)},
        {"role": "user", "content": "Your answer failed these checks:\n- " + "\n- ".join(problems)
         + "\nRewrite it using only the retrieved evidence. Cite every fact as [S#]. Do not use numbers, "
           "identifiers or quotations that are not in the cited evidence."}]
    try:
        draft = _call_model(client, model, retry_messages, "retry", usage, trace, max_tokens)
    except Exception as error:  # noqa: BLE001
        errors.append(f"model unavailable on retry ({type(error).__name__})")
        return build_template_answer(sources, question), ENDPOINT_DOWN_NOTE
    problems = _problems(draft, sources, question)
    trace.append({"step": "post_check", "attempt": 2, "problems": len(problems)})
    if not problems:
        return draft, None
    errors.append("model answer failed validation twice; template used")
    return build_template_answer(sources, question), UNVERIFIED_DRAFT_NOTE


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
    ambiguous = ambiguous_machines(question, all_sources)
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
    elif not any(character.isdigit() for character in question):
        retrieval_question = (previous + " " + question).strip()
    table_request = is_history_table_request(retrieval_question)
    combined = bool(re.search(r"\b(?:incident|near.miss)\b", retrieval_question, re.I)
                    and re.search(r"\b(?:service|servicing|work.order|maintenance)\b", retrieval_question, re.I))
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

    note = None
    if not sources:
        body, path = _no_evidence_text(retrieval_question, table_request, combined, failed), "no_evidence"
    elif combined:
        body, path = format_combined_history_table(sources), "table"
    elif table_request and is_work_order_table_request(retrieval_question):
        body, path = format_work_order_table(sources), "table"
    elif table_request:
        body, path = format_incident_table(sources), "table"
    else:
        extra = sanitize_sources(conflict_rules.related_sources(retrieval_question, sources, all_sources))
        sources = sources + [{**source, "id": f"S{len(sources) + position + 1}"} for position, source in enumerate(extra)]
        body, note = _model_answer(question, history, sources, sanitize_text(str(warnings)), client, model,
                                   usage, trace, errors, max_tokens)
        path = "template" if note else "model"
    trace.append({"step": "path", "path": path})

    found = conflict_rules.find_conflicts(sources, question)
    notes = mandatory_notes(flags, question, sources)
    notes += [item["text"] for item in found]
    if note:
        notes.append(note)
    if failed and sources:
        notes.append(f"I could not check {', '.join(failed)}; this answer uses only the sources that were available.")
    outcome = decide_outcome(flags=flags, has_evidence=bool(sources), failed_sources=failed, conflicts=found)
    trace.append({"step": "outcome", "outcome": outcome, "conflicts": len(found)})
    text = body + ("\n\nNotes:\n" + "\n".join(f"- {item}" for item in notes) if notes else "")
    return _finish(started, usage, trace, errors, answer=text, outcome=outcome, flags=flags, sources=sources,
                   notes=notes)
