"""Turn a short follow-up into a full question using the previous user turn.

"and in 2026?" after "How many incidents were there in 2025?" becomes "How many incidents were there in 2026?".
"and CNC-03?" after "What oil does CNC-02 take?" becomes "What oil does CNC-03 take?". A follow-up with no year or
machine is appended to the previous question, as before. A bare year after a partial-date question is handled by the
pipeline itself.
"""
from __future__ import annotations

import re

FOLLOW_UP = re.compile(r"^\s*(?:and|what about|how about|also|same for|now)\b", re.I)
YEAR = re.compile(r"\b20\d{2}\b")
TAG = re.compile(r"(?<![\w-])[A-Za-z]{2,6}-[A-Za-z]?\d{2,3}(?![\w-])")


def resolve_followup(question: str, previous: str) -> str | None:
    """The rewritten question, or None when the question is not a follow-up that needs rewriting."""
    if not previous or not FOLLOW_UP.match(question):
        return None
    rewritten = previous
    years, tags = YEAR.findall(question), TAG.findall(question)
    if len(years) == 1 and YEAR.search(previous):
        rewritten = YEAR.sub(years[0], rewritten)
    if len(tags) == 1 and TAG.search(previous):
        rewritten = TAG.sub(tags[0].upper(), rewritten)
    if rewritten != previous:
        return rewritten
    if years or tags:
        return f"{previous} {question}".strip()
    return None
