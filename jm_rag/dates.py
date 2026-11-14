"""Date parsing for questions: explicit days, windows and partial work-order dates."""
from __future__ import annotations

import re
from datetime import date, timedelta

from jm_rag.config import MONTH_NUMBERS
from jm_rag.intents import is_work_order_table_request


def parse_explicit_date(question: str) -> date | None:
    month_names = ("january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
                   "august|aug|september|sept?|october|oct|november|nov|december|dec")
    patterns = (
        (re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", re.I), "ymd"),
        (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})\b", re.I), "numeric_dmy"),
        (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})\s+(20\d{{2}})\b", re.I), "dmy"),
        (re.compile(rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+(20\d{{2}})\b", re.I), "mdy"),
    )
    for pattern, order in patterns:
        match = pattern.search(question)
        if not match:
            continue
        try:
            if order == "ymd":
                year, month, day = map(int, match.groups())
            elif order == "numeric_dmy":
                day, month, year = map(int, match.groups())
            elif order == "dmy":
                day, month_name, year = match.groups()
                month = MONTH_NUMBERS[month_name.casefold()]
                year, day = int(year), int(day)
            else:
                month_name, day, year = match.groups()
                month = MONTH_NUMBERS[month_name.casefold()]
                year, day = int(year), int(day)
            return date(year, month, day)
        except (KeyError, ValueError):
            return None
    return None


def parse_date_window(question: str) -> tuple[date, date] | None:
    exact_day = parse_explicit_date(question)
    if exact_day:
        return exact_day, exact_day + timedelta(days=1)

    month_names = ("january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|"
                   "august|aug|september|sept?|october|oct|november|nov|december|dec")
    month_range = re.search(
        rf"\b({month_names})\s*(?:-|–|—|to|through|until)\s*({month_names})\s*(20\d{{2}})\b",
        question, re.I,
    )
    if month_range:
        start_month = MONTH_NUMBERS[month_range.group(1).casefold()]
        end_month = MONTH_NUMBERS[month_range.group(2).casefold()]
        year = int(month_range.group(3))
        if end_month < start_month:
            return None
        return date(year, start_month, 1), date(year + (end_month == 12), end_month % 12 + 1, 1)

    year_range = re.search(r"\b(20\d{2})\s*(?:-|–|—|to|through|until)\s*(20\d{2})\b", question, re.I)
    if year_range:
        first_year, last_year = map(int, year_range.groups())
        if last_year < first_year:
            return None
        return date(first_year, 1, 1), date(last_year + 1, 1, 1)

    month_year = re.search(rf"\b({month_names})\s*(20\d{{2}})\b", question, re.I)
    if month_year:
        month = MONTH_NUMBERS[month_year.group(1).casefold()]
        year = int(month_year.group(2))
        return date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1)

    year_only = re.search(r"\b(?:in|during|year)\s+(20\d{2})\b", question, re.I)
    if year_only:
        year = int(year_only.group(1))
        return date(year, 1, 1), date(year + 1, 1, 1)
    return None


def partial_work_order_date(question: str) -> tuple[int, int, str] | None:
    if not is_work_order_table_request(question):
        return None
    patterns = (
        re.compile(r"(?<!\d)(\d{1,2})\s*[/.-]\s*(\d{1,2})(?!\s*[/.-]\s*\d{2,4})(?!\d)"),
        re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sept?|october|oct|november|nov|december|dec)\b(?!\s*,?\s*20\d{2})", re.I),
        re.compile(r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sept?|october|oct|november|nov|december|dec)\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*20\d{2})", re.I),
    )
    for index, pattern in enumerate(patterns):
        match = pattern.search(question)
        if not match:
            continue
        try:
            if index == 0:
                day, month = map(int, match.groups())
            elif index == 1:
                day = int(match.group(1))
                month = MONTH_NUMBERS[match.group(2).casefold()]
            else:
                month = MONTH_NUMBERS[match.group(1).casefold()]
                day = int(match.group(2))
            date(2000, month, day)
            return day, month, match.group(0)
        except (KeyError, ValueError):
            continue
    return None


def resolve_partial_work_order_date(question: str, year: int) -> str:
    partial = partial_work_order_date(question)
    if not partial:
        return question
    day, month, raw_date = partial
    normalized = f"{year:04d}-{month:02d}-{day:02d}"
    return re.sub(re.escape(raw_date), normalized, question, count=1)
