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


def is_aggregate_question(question: str) -> bool:
    """Counts, totals and extremes. These go to the model with the computed facts, not to a history table."""
    return bool(re.search(
        r"\b(?:how many|number of|count of|total|in total|sum of|average|mean|how much|altogether|combined|"
        r"cheapest|most expensive|costliest|highest|lowest|longest|shortest|cost|spend|spent|most|fewest|per|each)\b",
        question, re.I,
    ))
