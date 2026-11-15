"""Token and cost accounting for every model call, request logs, spend summary and budget limits.

- ``new_usage()`` starts the per-request record of the response contract; ``record_call()`` adds one model call
  (answer or retry). Prices come from OPENAI_INPUT_COST_PER_1M_USD and OPENAI_OUTPUT_COST_PER_1M_USD. With no
  known price the tokens are still recorded and the cost is None; a made-up figure is never shown.
- ``log_request()`` appends one line per question to logs/requests.jsonl: request ID, time, question length and a
  hash, guard class, retrieved source IDs, outcome, retries, latency per step, tokens and cost. No names, no
  question text, no answer text.
- ``log_spend()`` appends eval and other non-chat model calls to logs/spend.jsonl. Chat costs are stored with the
  chat messages in MySQL (``scripts/chat_history.py``).
- ``spend_summary()`` adds both sources for today, the last 7 days and all time, split by chat and eval.
- ``budget_status()`` reads DAILY_BUDGET_USD and TOTAL_BUDGET_USD (optional; unset means no limit).

Run ``python -m jm_rag.observability`` for the spend report.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

from jm_rag import config

WARNING_FRACTION = 0.8


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


# --- logs -------------------------------------------------------------------------------------------------

def logs_dir():
    return config.ROOT / "logs"


def _append(name: str, entry: dict) -> None:
    folder = logs_dir()
    folder.mkdir(exist_ok=True)
    with (folder / name).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str) + "\n")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def log_request(response: dict, question: str, *, request_id: str | None = None, source: str = "chat",
                chat_id: str | None = None) -> dict:
    """Append one request line. The question is stored only as its length and a hash; no answer text."""
    usage = response.get("usage") or new_usage()
    entry = {
        "request_id": request_id or new_request_id(), "ts": _now().isoformat(timespec="seconds"), "source": source,
        "chat_id": chat_id, "question_chars": len(question or ""),
        "question_sha256": hashlib.sha256((question or "").encode("utf-8")).hexdigest()[:16],
        "guard_class": response.get("refusal_class"), "outcome": response.get("outcome"),
        "sources": [{"id": s.get("id"), "type": s.get("source_type")} for s in response.get("sources", [])],
        "cited": list(response.get("cited_ids", [])), "notes": len(response.get("notes", [])),
        "retries": sum(1 for step in usage.get("steps", []) if step.get("step") == "retry"),
        "steps_ms": [{"step": step.get("step"), "ms": step.get("ms")} for step in usage.get("steps", [])],
        "total_ms": next((step.get("ms") for step in reversed(response.get("trace", [])) if step.get("step") == "done"), None),
        "calls": usage.get("calls", 0), "prompt": usage.get("prompt", 0), "completion": usage.get("completion", 0),
        "cost_usd": usage.get("cost_usd"), "errors": len(response.get("errors", [])),
    }
    _append("requests.jsonl", entry)
    return entry


def log_spend(*, source: str, usage: dict, model: str | None = None, ref: str | None = None, mode: str | None = None) -> dict | None:
    """Append a non-chat model spend line (evals and anything else that is not stored with a chat message)."""
    if not usage.get("calls"):
        return None
    entry = {"ts": _now().isoformat(timespec="seconds"), "source": source, "mode": mode, "case": ref, "model": model,
             "calls": usage["calls"], "prompt": usage.get("prompt", 0), "completion": usage.get("completion", 0),
             "cost_usd": usage.get("cost_usd")}
    _append("spend.jsonl", entry)
    return entry


def _read_jsonl(name: str) -> list[dict]:
    path = logs_dir() / name
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


# --- spend summary and budget ------------------------------------------------------------------------------

def _chat_rows(connection) -> list[dict]:
    """(created_at, cost_usd, token_count) of assistant messages from MySQL; [] when unavailable."""
    if connection is None:
        try:
            from scripts.chat_history import ensure_chat_schema
            from scripts.ocr_review import open_connection
            connection = open_connection()
            ensure_chat_schema(connection)
            own = True
        except Exception:  # noqa: BLE001 - the summary still works from the log files
            return []
    else:
        own = False
    try:
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute("SELECT created_at, cost_usd, token_count FROM chat_messages WHERE role='assistant'")
            return list(cursor.fetchall())
        finally:
            cursor.close()
    except Exception:  # noqa: BLE001
        return []
    finally:
        if own:
            connection.close()


def _as_utc(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def spend_summary(since: datetime | None = None, *, connection=None, chat_rows: list[dict] | None = None,
                  now: datetime | None = None) -> dict:
    """Spend for today, the last 7 days and all time (since ``since`` if given), split by chat and eval.

    Chat spend is read from chat_messages.cost_usd; eval and other spend from logs/spend.jsonl. Unpriced calls are
    counted under ``unpriced`` and never added as zero cost."""
    now = now or _now()
    today = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
    windows = {"today": today, "last_7_days": today - timedelta(days=6), "all_time": None}
    rows = []
    for row in chat_rows if chat_rows is not None else _chat_rows(connection):
        rows.append(("chat", _as_utc(row.get("created_at")), row.get("cost_usd"), int(row.get("token_count") or 0)))
    for row in _read_jsonl("spend.jsonl"):
        rows.append((row.get("source") or "other", _as_utc(row.get("ts")), row.get("cost_usd"),
                     int(row.get("prompt") or 0) + int(row.get("completion") or 0)))
    summary = {}
    for name, start in windows.items():
        bucket = {}
        for source, when, cost, tokens in rows:
            if when is None or (start and when < start) or (since and when < _as_utc(since)):
                continue
            entry = bucket.setdefault(source, {"cost_usd": 0.0, "tokens": 0, "entries": 0, "unpriced": 0})
            entry["entries"] += 1
            entry["tokens"] += tokens
            if cost is None:
                entry["unpriced"] += 1 if tokens else 0
            else:
                entry["cost_usd"] += float(cost)
        for source in ("chat", "eval"):
            bucket.setdefault(source, {"cost_usd": 0.0, "tokens": 0, "entries": 0, "unpriced": 0})
        bucket["total_usd"] = sum(value["cost_usd"] for key, value in bucket.items() if isinstance(value, dict))
        summary[name] = bucket
    return summary


def _limit(name: str) -> float | None:
    raw = os.getenv(name)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) and value >= 0 else None


def budget_status(summary: dict) -> dict:
    """{"daily": {...}, "total": {...}, "blocked": bool}. Each limit: limit, used, remaining, state (ok|warning|exceeded)."""
    status = {"blocked": False}
    for key, env, window in (("daily", "DAILY_BUDGET_USD", "today"), ("total", "TOTAL_BUDGET_USD", "all_time")):
        limit = _limit(env)
        used = summary[window]["total_usd"]
        if limit is None:
            status[key] = {"limit": None, "used": used, "remaining": None, "state": "no limit"}
            continue
        state = "exceeded" if used >= limit else ("warning" if used >= WARNING_FRACTION * limit else "ok")
        status[key] = {"limit": limit, "used": used, "remaining": max(0.0, limit - used), "state": state}
        status["blocked"] = status["blocked"] or state == "exceeded"
    return status


BUDGET_NOTE = "The model budget is used up, so this lists the retrieved evidence directly; no AI wording was generated."


# --- report ------------------------------------------------------------------------------------------------

def _money(value) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def report(out=print) -> None:
    summary = spend_summary()
    out(f"Spend report ({date.today():%d %b %Y}, UTC days). USD.")
    out(f"  {'window':<13}{'chat':>10}{'eval':>10}{'other':>10}{'total':>10}{'unpriced calls':>16}")
    for name in ("today", "last_7_days", "all_time"):
        bucket = summary[name]
        other = sum(v["cost_usd"] for k, v in bucket.items() if isinstance(v, dict) and k not in ("chat", "eval"))
        unpriced = sum(v["unpriced"] for k, v in bucket.items() if isinstance(v, dict))
        out(f"  {name:<13}{bucket['chat']['cost_usd']:>10.4f}{bucket['eval']['cost_usd']:>10.4f}{other:>10.4f}"
            f"{bucket['total_usd']:>10.4f}{unpriced:>16}")
    status = budget_status(summary)
    for key in ("daily", "total"):
        item = status[key]
        out(f"  {key} budget: " + ("no limit set" if item["limit"] is None else
                                   f"{item['used']:.4f} of {item['limit']:.4f} used ({item['state']})"))
    expensive = [(row.get("request_id"), row.get("cost_usd")) for row in _read_jsonl("requests.jsonl") if row.get("cost_usd")]
    expensive += [(f"eval {row.get('case')}", row.get("cost_usd")) for row in _read_jsonl("spend.jsonl") if row.get("cost_usd")]
    out("  five most expensive requests (ID, USD):")
    for ref, cost in sorted(expensive, key=lambda item: item[1], reverse=True)[:5]:
        out(f"    {ref}  {_money(cost)}")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(config.ROOT / ".env", override=True)
    report()
    sys.exit(0)
