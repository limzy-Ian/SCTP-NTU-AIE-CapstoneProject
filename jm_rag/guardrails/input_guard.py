"""Input guard. Phase 2 keeps the original input_refusal unchanged; Phase 3 replaces it."""
from __future__ import annotations

import re


def input_refusal(question: str) -> str | None:
    unsafe = re.search(
        r"\b(?:bypass|disable|ignore|skip|override|defeat)\b.{0,100}"
        r"\b(?:safety|interlock|loto|lockout|permit|procedure|guard)\b",
        question, re.I | re.S,
    )
    private = re.search(r"\b(?:nric|passport|salary|salaries|home address|phone number)\b", question, re.I)
    if unsafe:
        return "I cannot help bypass safety controls. Follow the approved SOP and consult the safety officer."
    if private:
        return "I cannot provide personnel or private information."
    return None
