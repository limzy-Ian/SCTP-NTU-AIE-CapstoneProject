"""Answer validation. Phase 2 keeps the original validate_answer unchanged; Phase 4 extends it."""
from __future__ import annotations

import re

from jm_rag.guardrails.input_guard import input_refusal


def validate_answer(answer: str, sources: list[dict]) -> str:
    cited = set(re.findall(r"\[(S\d+)\]", answer))
    allowed = {source["id"] for source in sources}
    if not cited or not cited.issubset(allowed):
        return "The generated answer lacked valid source citations. Please review the retrieved evidence below."
    if re.search(r"\b[STFGM]\d{7}[A-Z]\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", answer, re.I):
        return "The generated answer contained potentially private information and was withheld."
    if input_refusal(answer):
        return "The generated answer requires safety review and was withheld. Consult the approved SOP."
    return answer
