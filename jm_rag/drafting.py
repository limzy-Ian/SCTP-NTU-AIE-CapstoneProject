"""The model path: draft, check, one retry, then keep the figures or fall back to the template.

1. The model drafts an answer from the evidence.
2. Code checks it (``validator.post_check``, unsafe wording) and checks that every required value is stated: the
   figures from the computed facts that answer the question. An SOP the answer cites but does not name is named by
   code in a "Source:" line (no retry for that).
3. On any problem the model gets one retry with the full list of what failed and what is missing.
4. If the retry still breaks a check, the deterministic template answers. If the only problem left is a missing
   required value, the model's answer is kept and code appends a short cited "Key figures" line.
Every model call is recorded in ``usage``.
"""
from __future__ import annotations

import time

from jm_rag import observability, validator
from jm_rag.guardrails.sanitize import sanitize_text
from jm_rag.key_figures import key_figures_line, missing, required_from_facts, required_sop_ids
from jm_rag.prompt import load_system_prompt, serialize_evidence
from jm_rag.template import build_template_answer

NOT_CONFIGURED_NOTE = "The AI endpoint is not configured, so this lists the retrieved evidence directly."
ENDPOINT_DOWN_NOTE = "The AI endpoint is unavailable, so this lists the retrieved evidence directly."
UNVERIFIED_DRAFT_NOTE = ("The AI draft could not be verified against the evidence after one retry, so this lists "
                         "the retrieved evidence directly.")


def call_model(client, model, messages, step, usage, trace, max_tokens):
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


def problems_with(draft: str, sources: list[dict], question: str, flags: dict | None = None) -> list[str]:
    found = validator.post_check(draft, sources, question)
    if validator.unsafe_language(draft):
        found.append("The answer asks for or describes a safety bypass or private data. Remove it.")
    if (flags or {}).get("inference_request"):
        phrases = validator.condition_judgements(draft)
        if phrases:
            found.append("The question asks for a judgement the data cannot support. Do not use these phrases, not even in "
                         "a negated sentence: " + ", ".join(f'"{p}"' for p in phrases)
                         + ". Describe what the records show and say the data cannot judge the machine's condition.")
    return [sanitize_text(item) for item in found]


def required_values(retrieval_question: str, sources: list[dict]) -> list[dict]:
    facts = next((source for source in sources if source.get("source_type") == "computed_facts"), None)
    return required_from_facts(retrieval_question, facts)


def _missing_text(items: list[dict]) -> list[str]:
    return [f"State {item['label']}" + ("" if item.get("caveat") else f" ({item['options'][0]})") + f", citing [{item['source']}]."
            for item in items]


def model_answer(question, retrieval_question, history, sources, warnings, client, model, usage, trace, errors, max_tokens,
                 flags=None):
    """Return (answer, note). A note is set when the template was used instead of the model."""
    required = required_values(retrieval_question, sources)
    if client is None:
        return build_template_answer(sources, question, required), NOT_CONFIGURED_NOTE
    evidence = serialize_evidence(sources)
    messages = ([{"role": "system", "content": load_system_prompt()}] + history
                + [{"role": "user", "content": f"Question: {question}\nSource availability warnings: {warnings}\n"
                                               f"Retrieved evidence:\n{evidence}"}])
    try:
        draft = call_model(client, model, messages, "answer", usage, trace, max_tokens)
    except Exception as error:  # noqa: BLE001
        errors.append(f"model unavailable ({type(error).__name__})")
        return build_template_answer(sources, question, required), ENDPOINT_DOWN_NOTE
    problems = problems_with(draft, sources, question, flags)
    lacking = missing(draft, required)
    trace.append({"step": "post_check", "attempt": 1, "problems": len(problems), "missing_required": len(lacking)})
    if not problems and not lacking:
        return _name_sops(draft, sources, trace), None
    feedback = []
    if problems:
        feedback.append("Your answer failed these checks:\n- " + "\n- ".join(problems))
    if lacking:
        feedback.append("Your answer leaves out figures from the evidence that answer the question:\n- "
                        + "\n- ".join(_missing_text(lacking)))
    retry_messages = messages + [
        {"role": "assistant", "content": sanitize_text(draft)},
        {"role": "user", "content": "\n".join(feedback)
         + "\nRewrite the answer using only the retrieved evidence. Cite every fact as [S#]. State every figure listed "
           "above. Do not use numbers, identifiers or quotations that are not in the cited evidence."}]
    try:
        draft = call_model(client, model, retry_messages, "retry", usage, trace, max_tokens)
    except Exception as error:  # noqa: BLE001
        errors.append(f"model unavailable on retry ({type(error).__name__})")
        return build_template_answer(sources, question, required), ENDPOINT_DOWN_NOTE
    problems = problems_with(draft, sources, question, flags)
    lacking = missing(draft, required)
    trace.append({"step": "post_check", "attempt": 2, "problems": len(problems), "missing_required": len(lacking)})
    if problems:
        errors.append("model answer failed validation twice; template used")
        return build_template_answer(sources, question, required), UNVERIFIED_DRAFT_NOTE
    if lacking:
        trace.append({"step": "key_figures_appended", "values": len(lacking)})
        draft = draft.rstrip() + "\n\n" + key_figures_line(lacking)
    return _name_sops(draft, sources, trace), None


def _name_sops(draft: str, sources: list[dict], trace: list) -> str:
    """Name every SOP the answer cites but does not name, so the reader can find it. Code adds it; no retry."""
    unnamed = missing(draft, required_sop_ids(draft, sources))
    if not unnamed:
        return draft
    trace.append({"step": "sop_named", "sops": len(unnamed)})
    return draft.rstrip() + "\n\nSource: " + "; ".join(f"{item['label'][4:]} [{item['source']}]" for item in unnamed) + "."
