"""Deterministic answer built from the evidence, used when no model is available or the model keeps failing.

A short cited list of the most relevant facts. Every value is copied from the source record or text, so the
result passes ``post_check``. It adds nothing that is not in the sources.
"""
from __future__ import annotations

import re

from jm_rag.guardrails.sanitize import WITHHELD_TEXT, looks_like_instruction
from jm_rag.notes import record_of

MAX_ITEMS = 5
MAX_FACTS = 8
MAX_VALUE = 80
MAX_SNIPPET = 220
_SKIP_KEYS = {"ocr_raw_json", "image_path", "flags_json", "extraction_flags", "emp_code", "reviewer"}


def _short(value: str, limit: int) -> str:
    if looks_like_instruction(value):
        return WITHHELD_TEXT
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "..."


_TOPICS = (   # a question word -> the facts clauses about that topic
    (r"vibrat\w*", r"vibration"), (r"temperat\w*|fahrenheit|celsius", r"temperature|fahrenheit|celsius"),
    (r"\bcosts?\b|\bspen[dt]\b|how much|expensive|cheap\w*", r"\bcost\b|expensive|cheapest|currency"),
    (r"\bhours?\b|duration|how long", r"duration"), (r"lost days?", r"lost days"), (r"\btypes?\b", r"by type"),
    (r"\bstatus\b", r"by status"), (r"\bwhen\b|\bdates?\b|\brange\b", r"\bdated\b"),
)
_STOP = {"what", "which", "where", "when", "does", "have", "with", "there", "about", "from", "this", "that", "they",
         "were", "will", "your", "show", "tell", "give", "many", "much", "need", "into", "only", "machine", "machines"}


def _clauses(text: str) -> list[str]:
    body = re.sub(r"^Facts computed by code from all matching records, not only the ones shown\. "
                  r"Use these for counts, totals, minima, maxima and date ranges\. ", "", text.strip())
    return [clause.strip() for clause in re.split(r";\s+|(?<=\.)\s+(?=[A-Z])", body) if clause.strip()]


def _relevant_facts(source: dict, question: str, required: list[dict]) -> str:
    """Only the facts clauses that answer the question: a group's header, the clauses holding a required value,
    and the clauses on a topic the question names. The full facts stay in the evidence panel."""
    from jm_rag.key_figures import stated

    wanted = [item for item in required if item.get("source") == source.get("id")]
    topics = [clause_pattern for question_pattern, clause_pattern in _TOPICS if re.search(question_pattern, question, re.I)]
    keep = []
    for clause in _clauses(str(source.get("text") or "")):
        header = bool(re.match(r"(Work orders|Incidents|Spare parts|Sensor months|Nameplate lubricant) ", clause))
        if (header or any(stated(clause, item["options"]) for item in wanted)
                or any(re.search(pattern, clause, re.I) for pattern in topics)):
            keep.append(clause.rstrip("."))
    return "; ".join(keep)


_WHOLE_SOP = re.compile(r"\b(?:procedures?|steps?|what do i need|rules?|before|how do i|requirements?|checklist|"
                        r"summari[sz]e)\b", re.I)
_LINE_TYPES = {"document", "processed_audit", "sensor_trend_monthly", "sensor_shift_monthly"}


def _document_lines(source: dict, question: str) -> str:
    """The lines of a text source that share the most words with the question (up to five, in document order;
    ties go to the later lines, which for monthly sensor sources are the most recent months). A procedure question
    gets the whole SOP, which is short."""
    text = str(source.get("text") or "")
    if source.get("source_type") == "document" and str(source.get("title", "")).upper().startswith("SOP") and _WHOLE_SOP.search(question):
        return _short(re.sub(r"\s*\n\s*", " / ", text.strip()), 4 * MAX_SNIPPET)
    stems = {word[:5].lower() for word in re.findall(r"[A-Za-z]{4,}", question) if word.lower() not in _STOP}
    lines = [line.strip(" -*") for line in text.splitlines() if line.strip(" -*")]
    scored = [(sum(1 for stem in stems if stem in line.lower()), index) for index, line in enumerate(lines)]
    best = sorted(index for score, index in sorted(scored, reverse=True)[:5] if score > 0)
    if not best:
        return ""
    return _short(" / ".join(lines[index] for index in best), 3 * MAX_SNIPPET)


def _facts(source: dict, question: str = "", required: list[dict] | None = None) -> str:
    if source.get("source_type") == "computed_facts":
        return _relevant_facts(source, question, required or [])
    if source.get("source_type") in _LINE_TYPES and question:
        picked = _document_lines(source, question)
        if picked:
            return picked
    record = record_of(source)
    parts = []
    for key, value in record.items():
        if key in _SKIP_KEYS or value in (None, "") or isinstance(value, (dict, list)):
            continue
        parts.append(f"{key}={_short(str(value), MAX_VALUE)}")
        if len(parts) >= MAX_FACTS:
            break
    if parts:
        return "; ".join(parts)
    text = str(source.get("text") or "")
    brace = text.find("{")
    return _short(text[:brace] if brace != -1 else text, MAX_SNIPPET).rstrip(".")


def build_template_answer(sources: list[dict], question: str = "", required: list[dict] | None = None) -> str:
    """A cited, evidence-only answer. ``sources`` are the retrieved sources (each with an id)."""
    usable = [source for source in sources if source.get("id") and str(source.get("text") or "").strip()]
    if not usable:
        return ("I could not find evidence to answer that question. "
                "Specify an asset tag, report ID or SOP topic and I will look again.")
    lines = ["Here is what the retrieved records show (no AI wording was generated):", ""]
    computed = [source for source in usable if source.get("source_type") == "computed_facts"]
    for source in [s for s in usable if s.get("source_type") != "computed_facts"][:MAX_ITEMS] + computed:
        title = re.sub(r"\s+", " ", str(source.get("title") or "")).strip()
        label = " (unverified OCR)" if "UNVERIFIED" in str(source.get("text") or "")[:40] else ""
        facts = _facts(source, question, required)
        detail = f": {facts}" if facts else ""
        lines.append(f"- {title}{label}{detail} [{source['id']}]")
    lines.append("")
    lines.append("These are the records themselves; see the evidence panel for the full text.")
    return "\n".join(lines)
