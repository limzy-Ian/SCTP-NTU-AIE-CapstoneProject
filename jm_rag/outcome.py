"""Outcome rules, decided in code in a fixed order (plan section 5.3).

1. refuse   the input guard matched, or the output guard replaced the answer
2. clarify  the question is ambiguous in a way the data supports asking about
3. abstain  no usable evidence, a gap code found (a plate field not read or implausible, no SOP on the topic,
            an identity question), or the question asks about the future, a missing document, a schedule or an inference (the facts that exist are still shown, with the gap stated)
4. conflict two sources disagree and both are in the evidence
5. error    every source failed (checked together with rule 3: no evidence plus a failed source is an
            error, not an abstain, because "no records" cannot be told from "could not check")
6. answer   otherwise
"""
from __future__ import annotations

ABSTAIN_FLAGS = ("needs_future_date", "asks_missing_document", "asks_schedule", "inference_request")


def decide_outcome(*, refused: bool = False, output_blocked: bool = False, clarify: bool = False,
                   flags: dict | None = None, has_evidence: bool = True, failed_sources: list[str] | None = None,
                   conflicts: list[dict] | None = None, gap: bool = False) -> str:
    flags = flags or {}
    if refused or output_blocked:
        return "refuse"
    if clarify:
        return "clarify"
    if not has_evidence and failed_sources:
        return "error"
    if not has_evidence or gap or any(flags.get(flag) for flag in ABSTAIN_FLAGS):
        return "abstain"
    if any(conflict.get("disagrees") for conflict in (conflicts or [])):
        return "conflict"
    return "answer"
