r"""Build data/guard/name_terms.json from the CMMS ``employees`` table.

Run:  .\.venv\Scripts\python.exe -m scripts.build_guard_terms

Reads ``employees.emp_name`` (read-only) and writes the names the guardrails must keep out
of answers and evidence. Names found in the optional ``data/guard/extra_terms.txt`` (one per
line, for people who are not in the employees table) are added. The output file is
git-ignored (``data/*``). This script prints only counts, never a name, and error messages
carry only the exception type.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jm_rag import config
from scripts.ocr_review import open_connection

MIN_TERM_LENGTH = 5


def variants(full_name: str) -> set[str]:
    """The name as stored, plus 'last first' order for multi-word names."""
    words = full_name.split()
    found = {" ".join(words)}
    if len(words) >= 2:
        found.add(" ".join([words[-1], *words[:-1]]))
    return {term for term in found if len(term) >= MIN_TERM_LENGTH}


def build_terms(raw_names: list[str], extra: list[str] | None = None) -> list[str]:
    terms: set[str] = set()
    for value in [*raw_names, *(extra or [])]:
        if value and str(value).strip():
            terms |= variants(str(value).strip())
    return sorted(terms, key=str.casefold)


def read_employee_names() -> list[str]:
    connection = open_connection()
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT DISTINCT emp_name FROM employees WHERE emp_name IS NOT NULL")
            return [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
    finally:
        connection.close()


def read_extra_terms(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def write_terms(terms: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"terms": terms, "count": len(terms),
               "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")


def main() -> int:
    target = config.guard_terms_path()
    try:
        raw_names = read_employee_names()
    except Exception as error:  # noqa: BLE001 - only the type is printed, never the message
        print(f"Could not read employees from MySQL ({type(error).__name__}). No file written.")
        return 1
    extra = read_extra_terms(target.parent / "extra_terms.txt")
    terms = build_terms(raw_names, extra)
    if not terms:
        print("No names found in employees; no file written.")
        return 1
    write_terms(terms, target)
    print(f"Wrote {len(terms)} guard terms from {len(raw_names)} employee names "
          f"and {len(extra)} extra terms to {target.relative_to(config.ROOT).as_posix()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
