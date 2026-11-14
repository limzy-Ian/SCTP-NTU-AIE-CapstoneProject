"""Machine tags in a question, checked against the machines the data actually holds.

A tag-shaped word (CNC-02, PMP-T01, TST-99) is a machine tag when its prefix belongs to a known machine type.
It is *valid* when a loaded source carries it, otherwise *unknown*, and an unknown tag must give an honest
"no such machine" instead of other machines' records. Part numbers and report IDs are not tags: a tag-shaped
word that is part of a longer hyphenated code (PN-FAKE-100, IR-2025-906) is ignored.
"""
from __future__ import annotations

import re

from jm_rag.config import ASSET_PATTERN

TAG_SHAPE = re.compile(r"(?<![\w-])([A-Za-z]{2,6})-([A-Za-z]?\d{2,3})(?![\w-])")
# machine types the plant is known to have, used even when no loaded source carries a tag with that prefix
LEGACY_PREFIXES = {"CNC", "CRN", "LTH", "MILL", "PMP", "WELD", "BLAST", "CMP"}
SENSOR_TYPES = {"sensor_summary", "sensor_trend_monthly", "processed_sensor_summary", "processed_sensor_gaps"}


def _tags_of(source: dict) -> set[str]:
    values = source.get("asset_tags")
    if values is None:
        values = [source["asset_tag"]] if source.get("asset_tag") else []
    return {str(value).upper() for value in values if value}


def known_tags(sources: list[dict]) -> set[str]:
    found: set[str] = set()
    for source in sources:
        found |= _tags_of(source)
    return found


def machine_tags(sources: list[dict]) -> list[str]:
    """Tags of the machine master records, for "known machines" messages."""
    return sorted({str(source["asset_tag"]).upper() for source in sources
                   if source.get("machine_record") and source.get("asset_tag")})


def sensor_tags(sources: list[dict]) -> set[str]:
    found: set[str] = set()
    for source in sources:
        if source.get("source_type") in SENSOR_TYPES:
            found |= _tags_of(source)
    return found


def question_tags(question: str, sources: list[dict]) -> tuple[set[str], set[str]]:
    """(valid, unknown) machine tags written in the question, upper case."""
    known = known_tags(sources)
    prefixes = {tag.split("-", 1)[0] for tag in known if "-" in tag}
    prefixes |= LEGACY_PREFIXES
    written = {match.upper() for match in ASSET_PATTERN.findall(question)}
    for prefix, rest in TAG_SHAPE.findall(question):
        if prefix.upper() in prefixes:
            written.add(f"{prefix}-{rest}".upper())
    if not known:
        return written, set()
    return {tag for tag in written if tag in known}, {tag for tag in written if tag not in known}
