"""Token and cost accounting for every model call.

``new_usage()`` starts the per-request record described in the response contract;
``record_call()`` adds one model call (answer or retry) to it. Prices come from
OPENAI_INPUT_COST_PER_1M_USD and OPENAI_OUTPUT_COST_PER_1M_USD. With no known price the
tokens are still recorded and the cost is None; a made-up figure is never shown.
"""
from __future__ import annotations

import math
import os


def api_cost_rates(model):
    input_rate = os.getenv("OPENAI_INPUT_COST_PER_1M_USD")
    output_rate = os.getenv("OPENAI_OUTPUT_COST_PER_1M_USD")
    if input_rate is not None or output_rate is not None:
        if input_rate is None or output_rate is None:
            return None
        try:
            rates = float(input_rate), float(output_rate)
        except ValueError:
            return None
        return rates if all(math.isfinite(rate) and rate >= 0 for rate in rates) else None
    if not os.getenv("OPENAI_BASE_URL") and model == "gpt-4o-mini":
        return 0.15, 0.60
    return None


def estimate_api_cost(usage, model):
    rates = api_cost_rates(model)
    if usage is None or rates is None:
        return None
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


def new_usage() -> dict:
    return {"calls": 0, "prompt": 0, "completion": 0, "cost_usd": None, "steps": []}


def record_call(usage: dict, step: str, model: str, response_usage, milliseconds: int,
                error: str | None = None) -> dict:
    """Add one model call to ``usage``. A call that raised is counted too, with zero tokens."""
    prompt = int(getattr(response_usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(response_usage, "completion_tokens", 0) or 0)
    cost = estimate_api_cost(response_usage, model)
    entry = {"step": step, "model": model, "prompt": prompt, "completion": completion,
             "ms": int(milliseconds), "cost_usd": cost}
    if error:
        entry["error"] = error
    usage["steps"].append(entry)
    usage["calls"] += 1
    usage["prompt"] += prompt
    usage["completion"] += completion
    known = [step_entry["cost_usd"] for step_entry in usage["steps"] if step_entry["cost_usd"] is not None]
    usage["cost_usd"] = sum(known) if known else None
    return entry
