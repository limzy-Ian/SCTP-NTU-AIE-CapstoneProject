"""Checks applied to one case result. Pure functions, no model and no database."""
from __future__ import annotations

import re


def norm(text: str) -> str:
    """Lower case; commas inside numbers are ignored (4,057.24 equals 4057.24)."""
    return re.sub(r"(?<=\d),(?=\d)", "", text.lower())


def has(text: str, spec: str) -> bool:
    """True when the text holds the spec. ``a|b`` means either."""
    haystack = norm(text)
    return any(norm(option.strip()) in haystack for option in spec.split("|"))


def cited_matches(spec: str, cited_sources: list[dict]) -> bool:
    """``type:fragment`` (or ``type:fragment|type2:fragment2``): a cited source of that type whose title contains the fragment."""
    for option in spec.split("|"):
        source_type, _, fragment = option.partition(":")
        for source in cited_sources:
            if source.get("source_type") == source_type.strip() and fragment.strip().lower() in str(source.get("title", "")).lower():
                return True
    return False


def check_case(case: dict, result: dict, *, evidence_in_text: bool, llm_allowed: bool) -> list[str]:
    """Return the list of failures for one case result (an empty list means it passed).

    ``evidence_in_text``: no model wrote the answer, so ``must_include`` may be found in the retrieved evidence
    (including the computed facts) as well as in the answer. ``llm_allowed``: ``llm_include`` applies.
    """
    fails: list[str] = []
    answer = result["answer"]
    if "expect" in case and result["outcome"] != case["expect"]:
        fails.append(f"outcome {result['outcome']}, wanted {case['expect']}")
    if case.get("expect_not") and result["outcome"] == case["expect_not"]:
        fails.append(f"outcome was {result['outcome']}, which must not happen")
    haystack = answer
    if evidence_in_text:
        haystack += "\n" + "\n".join(f"{s.get('title', '')} {s.get('text', '')}" for s in result.get("sources", []))
    for spec in case.get("must_include", []):
        if not has(haystack, spec):
            fails.append(f"missing: {spec}")
    if llm_allowed:
        for spec in case.get("llm_include", []):
            if not has(answer, spec):
                fails.append(f"missing: {spec}")
    for spec in case.get("must_not_include", []):
        if has(answer, spec):
            fails.append(f"must not say: {spec}")
    cited = [s for s in result.get("sources", []) if s.get("id") in set(result.get("cited_ids", []))]
    for spec in case.get("must_cite", []):
        if not cited_matches(spec, cited):
            fails.append(f"not cited: {spec}")
    if case.get("no_llm") and result["usage"]["calls"] > 0:
        fails.append("a model was called")
    return fails
