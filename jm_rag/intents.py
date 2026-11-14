"""Question intent helpers shared by dates, tables and retrieval."""
from __future__ import annotations

import re


def is_work_order_table_request(question: str) -> bool:
    return bool(re.search(
        r"\b(?:work\s*orders?|service\s+records?|servic(?:e|ing)(?:\s+history)?|"
        r"maintenance\s+history|repair\s+history)\b",
        question, re.I,
    ))


def is_incident_query(question: str) -> bool:
    return bool(re.search(r"\b(?:incidents?|near.miss(?:es)?|severity|lost.days|injur(?:y|ies))\b", question, re.I))


def is_history_table_request(question: str) -> bool:
    if is_work_order_table_request(question):
        return True
    return is_incident_query(question) and bool(re.search(r"\b(?:table|tabular|list)\b", question, re.I))
