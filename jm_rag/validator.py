"""Answer validation done by code, not by the model.

``post_check`` returns every problem found in a draft answer so that one retry can fix them all:
citations must exist, numbers and identifiers must come from the cited evidence (or the question),
and a long quotation must appear word for word in a cited source. ``validate_answer`` is the older
single-message check and is kept for existing callers.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from jm_rag.guardrails.input_guard import unsafe_text_message

CITATION = re.compile(r"\[(S\d+)\]")
# hyphenated codes with a digit (CNC-02, IR-2025-906, PN-100, SOP-CRANE-02) and letter+digit codes (GA30, EMP015)
IDENTIFIER = re.compile(r"\b(?:[A-Za-z]{2,}[A-Za-z0-9]*(?:-[A-Za-z0-9]+)+|[A-Za-z]{2,}\d{2,}[A-Za-z0-9]*)\b")
NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*]\s*)?\d{1,2}[.)]\s")
QUOTE = re.compile(r"\"([^\"\n]+)\"|\u201c([^\u201d\n]+)\u201d")
MIN_QUOTE_WORDS = 4
# an answer that only says it could not find or cannot give something needs no citation
NON_FACTUAL = re.compile(
    r"^\W*(?:i (?:could not|couldn't|cannot|can't|do not|don't|am unable|was unable)|no (?:matching|records?|evidence|data|sources?)|"
    r"the (?:evidence|data|records?|sources?) (?:does|do|did) not|there (?:is|are|was|were) no|unable to|not enough)",
    re.I)


def _has_digit(token: str) -> bool:
    return any(character.isdigit() for character in token)


def _identifiers(text: str) -> set[str]:
    return {match.group(0).casefold() for match in IDENTIFIER.finditer(text) if _has_digit(match.group(0))}


def _number_key(token: str) -> str | None:
    try:
        return format(Decimal(token.replace(",", "")).normalize(), "f")
    except InvalidOperation:
        return None


def _numbers(text: str) -> set[str]:
    # evidence side: digits inside codes count too, so "906" is allowed when the source says IR-2025-906
    return {key for key in (_number_key(match.group(0)) for match in NUMBER.finditer(text)) if key is not None}


def _source_text(source: dict) -> str:
    return " ".join(str(source.get(key) or "") for key in ("title", "text", "location"))


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", CITATION.sub(" ", text)).strip().casefold()


def is_non_factual(answer: str) -> bool:
    """True when the answer only reports that something could not be found or given."""
    return bool(NON_FACTUAL.search(answer.strip()))


def cited_ids(answer: str) -> list[str]:
    seen: list[str] = []
    for identifier in CITATION.findall(answer):
        if identifier not in seen:
            seen.append(identifier)
    return seen


def post_check(answer: str, sources: list[dict], question: str = "") -> list[str]:
    """Return a list of problems with the draft answer; an empty list means it passed."""
    errors: list[str] = []
    text = answer or ""
    if not text.strip():
        return ["The answer is empty."]
    by_id = {source.get("id"): source for source in sources}
    cited = cited_ids(text)
    unknown = [identifier for identifier in cited if identifier not in by_id]
    for identifier in unknown:
        errors.append(f"Citation [{identifier}] does not exist in the retrieved evidence.")
    if not cited and not is_non_factual(text):
        errors.append("The answer has no [S#] citation. Cite each fact with the source ID.")

    known = [by_id[identifier] for identifier in cited if identifier in by_id]
    pool_sources = known if known else list(sources)
    pool = " ".join(_source_text(source) for source in pool_sources) + " " + (question or "")

    body = LIST_MARKER.sub(" ", CITATION.sub(" ", text))
    allowed_numbers = _numbers(pool) | {"0"}
    for number in sorted({match.group(0) for match in NUMBER.finditer(IDENTIFIER.sub(" ", body))}):
        key = _number_key(number)
        if key is not None and key not in allowed_numbers:
            errors.append(f"The number {number} is not in the cited sources or the question.")

    allowed_identifiers = _identifiers(pool)
    for match in IDENTIFIER.finditer(body):
        token = match.group(0)
        if _has_digit(token) and token.casefold() not in allowed_identifiers:
            message = f"The identifier {token} is not in the cited sources or the question."
            if message not in errors:
                errors.append(message)

    haystack = _normalise(" ".join(_source_text(source) for source in pool_sources))
    for match in QUOTE.finditer(text):
        quoted = match.group(1) or match.group(2)
        if len(quoted.split()) >= MIN_QUOTE_WORDS and _normalise(quoted) not in haystack:
            errors.append(f"The quoted text \"{quoted[:60]}\" does not appear word for word in a cited source.")
    return errors


# Condition judgements the data cannot support. For a question flagged as an inference request the answer must not use
# any of these, not even negated ("cannot be concluded that it is in good shape"): the reader takes away the phrase.
CONDITION_JUDGEMENTS = (
    "in good shape", "in bad shape", "in poor shape", "good shape", "bad shape",
    "good condition", "poor condition", "bad condition", "fine condition",
    "healthy", "unhealthy", "in good health", "good health",
    "safe to run", "safe to use", "safe to operate", "unsafe to run", "unsafe to use", "unsafe to operate",
    "no problems", "no issues", "working fine", "running fine", "nothing wrong",
)
_CONDITION = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(p) for p in CONDITION_JUDGEMENTS) + r")(?![a-z])", re.I)


def condition_judgements(answer: str) -> list[str]:
    """The condition-judgement phrases used in the answer, lower case, in order of first use."""
    found: list[str] = []
    for match in _CONDITION.finditer(answer or ""):
        phrase = match.group(0).lower()
        if phrase not in found:
            found.append(phrase)
    return found


def validate_answer(answer: str, sources: list[dict]) -> str:
    cited = set(re.findall(r"\[(S\d+)\]", answer))
    allowed = {source["id"] for source in sources}
    if not cited or not cited.issubset(allowed):
        return "The generated answer lacked valid source citations. Please review the retrieved evidence below."
    if re.search(r"\b[STFGM]\d{7}[A-Z]\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", answer, re.I):
        return "The generated answer contained potentially private information and was withheld."
    if unsafe_text_message(answer):
        return "The generated answer requires safety review and was withheld. Consult the approved SOP."
    return answer


def unsafe_language(answer: str) -> str | None:
    """Short reason when the draft asks for or describes a safety bypass or private data, else None."""
    return unsafe_text_message(answer)
