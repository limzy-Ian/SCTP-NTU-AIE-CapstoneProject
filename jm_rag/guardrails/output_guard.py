"""Output guard: the last check before text leaves the system. No model.

Scans for full employee names, national ID numbers, API keys and internal markers. On a
hit the answer is replaced by a safe refusal. The matched text is never returned or
logged, only the kind of leak. ``names_unloaded`` is set when the name list is missing,
so the caller can show a warning; the other checks still run.
"""
from __future__ import annotations

import logging

from jm_rag.guardrails import names

LOGGER = logging.getLogger("jm_rag.guardrails")

SAFE_REFUSAL = (
    "I cannot show that answer because it may contain personal or internal information. "
    "I can give aggregate counts by year, machine, shift or severity instead."
)


def check(answer: str) -> dict:
    """Return {ok, reason, answer, names_unloaded}. When not ok, answer is the safe refusal."""
    reason = names.leak_reason(answer)
    unloaded = not names.terms_loaded()
    if reason:
        LOGGER.warning("Output guard blocked an answer (leak kind: %s).", reason)
        return {"ok": False, "reason": reason, "answer": SAFE_REFUSAL, "names_unloaded": unloaded}
    return {"ok": True, "reason": None, "answer": answer, "names_unloaded": unloaded}
