r"""Compare this repo's processed OCR with the team's checked reference readings, field by field. No model calls.

Run:  .\.venv\Scripts\python.exe -m scripts.ocr_accuracy_report

Reference: data/extraction/06_images_extraction.csv (git-ignored client data). Compared:
- nameplates: data/processed/nameplates/nameplate_*.json (structured fields), with the raw OCR text next to each
  label (nameplate_*.txt) reported separately for lubricant and grease interval;
- incident forms: data/processed/incident_reports/incident_reports_ocr_full.jsonl (date, machine, severity, lost days,
  how reported). Employee codes and free-text descriptions are never compared or read out.

The output is counts by field and the machine IDs (or report IDs) with the field names that disagree. It never prints
a value and never an employee code. Do not commit its output.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from jm_rag import config

REFERENCE = Path("data") / "extraction" / "06_images_extraction.csv"
NAMEPLATE_FIELDS = {          # reference key -> processed OCR key
    "make": "manufacturer", "model": "model", "serial": "serial_number", "mfg": "manufactured_ym", "power": "power_kw",
    "FLA": "fla_amps", "max_speed": "max_speed_rpm", "weight": "weight_kg", "capacity": "capacity_raw",
    "lubricant": "lubricant", "grease_interval": "grease_interval_hours",
}
RAW_LABELS = {"lubricant": re.compile(r"\b\w*BRICANT\W+([^\n]{3,40})", re.I),
              "grease_interval": re.compile(r"\bGREASE\s+INTERVAL\W+(\d[\d,]*)", re.I)}
NUMERIC = {"power", "FLA", "max_speed", "weight", "grease_interval"}


def _alnum(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _first_number(value) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def _lubricant_key(value) -> str:
    text = str(value)
    grade = re.search(r"\bv?g\s?(\d{2,3})\b", text, re.I)
    if grade:
        return "VG" + grade.group(1)
    return "TONNA" if re.search(r"tonna", text, re.I) else _alnum(text)


def _month(value) -> str | None:
    text = str(value)
    match = re.search(r"(\d{1,2})\s*/\s*(\d{4})", text) or re.search(r"(\d{4})-(\d{1,2})", text)
    if not match:
        return None
    a, b = match.groups()
    month, year = (a, b) if len(b) == 4 else (b, a)
    return f"{int(year):04d}-{int(month):02d}"


def same(field: str, reference, ocr) -> bool:
    if ocr in (None, ""):
        return False
    if field in NUMERIC:
        return _first_number(reference) == _first_number(ocr)
    if field == "lubricant":
        return _lubricant_key(reference) == _lubricant_key(ocr)
    if field == "mfg":
        return _month(reference) == _month(ocr)
    if field == "model":
        return _alnum(reference) in _alnum(ocr) or _alnum(ocr) in _alnum(reference)
    if field in ("serial", "make"):   # OCR noise around the value is tolerated; the value itself must be there
        return bool(_alnum(reference)) and _alnum(reference) in _alnum(ocr)
    if field == "capacity":
        return _first_number(reference) == _first_number(ocr) and _alnum(reference)[-2:] == _alnum(ocr)[-2:]
    return _alnum(reference) == _alnum(ocr)


def _key_values(text: str) -> dict[str, str]:
    pairs = (part.partition("=") for part in text.split(";"))
    return {key.strip(): value.strip() for key, sep, value in pairs if sep}


def load_reference(root: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    path = root / REFERENCE
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    plates, forms = {}, {}
    for row in rows:
        if row["type"] == "nameplate":
            plates[row["asset_or_incident"].strip().upper()] = _key_values(row["extracted_fields"])
        elif row["type"] == "incident_form":
            parts = [part.strip() for part in row["extracted_fields"].split(";")]
            values = _key_values(row["extracted_fields"])
            # positions: date; machine; employee code; description; sev=; lost=; how reported; 5why=
            # the employee code and the description are deliberately not kept
            forms[Path(row["file"]).stem.upper()] = {"date": parts[0] if parts else "", "machine": parts[1] if len(parts) > 1 else "",
                                                     "sev": values.get("sev", ""), "lost": values.get("lost", ""),
                                                     "reporting": parts[6] if len(parts) > 6 else ""}
    return plates, forms


def compare_nameplates(root: Path, reference: dict[str, dict]) -> tuple[Counter, dict[str, list[str]], Counter, dict[str, list[str]]]:
    folder = root / "data" / "processed" / "nameplates"
    counts, wrong, raw_counts, raw_wrong = Counter(), {}, Counter(), {}
    for tag, expected in sorted(reference.items()):
        path = folder / f"nameplate_{tag}.json"
        asset = json.loads(path.read_text(encoding="utf-8")).get("asset", {}) if path.is_file() else {}
        raw_path = path.with_suffix(".txt")
        raw = raw_path.read_text(encoding="utf-8-sig") if raw_path.is_file() else ""
        for field, value in expected.items():
            if field not in NAMEPLATE_FIELDS:
                continue
            got = asset.get(NAMEPLATE_FIELDS[field])
            result = "match" if same(field, value, got) else ("missing" if got in (None, "") else "wrong")
            counts[(field, result)] += 1
            if result != "match":
                wrong.setdefault(tag, []).append(field)
            if field in RAW_LABELS:
                match = RAW_LABELS[field].search(raw)
                raw_result = "match" if match and same(field, value, match.group(1)) else ("missing" if not match else "wrong")
                raw_counts[(field, raw_result)] += 1
                if raw_result != "match":
                    raw_wrong.setdefault(tag, []).append(field)
    return counts, wrong, raw_counts, raw_wrong


def compare_forms(root: Path, reference: dict[str, dict]) -> tuple[Counter, dict[str, list[str]]]:
    path = root / "data" / "processed" / "incident_reports" / "incident_reports_ocr_full.jsonl"
    ocr = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                ocr[str(row.get("report_no", "")).upper()] = row
    counts, wrong = Counter(), {}
    for key, expected in sorted(reference.items()):
        got = ocr.get(key, {})
        checks = {
            "date": str(got.get("incident_date") or "")[:10] == expected["date"][:10] and bool(expected["date"]),
            "machine": _alnum(got.get("machine_id") or "") == _alnum(expected["machine"]),
            "severity": (str(got.get("severity_raw")) == expected["sev"]) if re.fullmatch(r"\d", expected["sev"] or "") else None,
            "lost_days": _first_number(got.get("lost_days")) == _first_number(expected["lost"]),
            "reporting": _alnum(got.get("reporting") or "") == _alnum(expected["reporting"]),
        }
        for field, ok in checks.items():
            if ok is None:
                counts[(field, "reference not legible")] += 1
                continue
            result = "match" if ok else ("missing" if not got or got.get(_FORM_KEYS[field]) in (None, "") else "wrong")
            counts[(field, result)] += 1
            if result != "match":
                wrong.setdefault(key, []).append(field)
    return counts, wrong


_FORM_KEYS = {"date": "incident_date", "machine": "machine_id", "severity": "severity_raw", "lost_days": "lost_days",
              "reporting": "reporting"}


def disagreements(root: Path | None = None) -> set[str]:
    """{"CNC-02:grease_interval", "IR-2026-955:severity", ...}: where the processed OCR disagrees with the reference.
    A nameplate field counts as wrong only when both the structured field and the raw OCR text next to its label miss."""
    root = root or config.ROOT
    if not (root / REFERENCE).is_file():
        return set()
    plates, forms = load_reference(root)
    _, wrong, _, raw_wrong = compare_nameplates(root, plates)
    found = set()
    for tag, fields in wrong.items():
        for field in fields:
            if field not in RAW_LABELS or field in raw_wrong.get(tag, []):
                found.add(f"{tag}:{field}")
    _, form_wrong = compare_forms(root, forms)
    found |= {f"{key}:{field}" for key, fields in form_wrong.items() for field in fields}
    return found


def _table(title: str, counts: Counter) -> None:
    fields = sorted({field for field, _ in counts})
    results = sorted({result for _, result in counts})
    print(f"\n{title}")
    print(f"  {'field':<18}" + "".join(f"{result:>23}" for result in results))
    for field in fields:
        print(f"  {field:<18}" + "".join(f"{counts.get((field, result), 0):>23}" for result in results))
    total = sum(counts.values())
    matched = sum(count for (_, result), count in counts.items() if result == "match")
    print(f"  {matched} of {total} field readings match ({100 * matched / total:.0f}%)" if total else "  nothing compared")


def main() -> int:
    root = config.ROOT
    if not (root / REFERENCE).is_file():
        print(f"Reference file {REFERENCE.as_posix()} not found.")
        return 1
    plates, forms = load_reference(root)
    counts, wrong, raw_counts, raw_wrong = compare_nameplates(root, plates)
    form_counts, form_wrong = compare_forms(root, forms)
    print(f"OCR accuracy against the checked reference readings ({date.today():%d %b %Y}). Counts only; no values shown.")
    print(f"Reference rows: {len(plates)} nameplates, {len(forms)} incident forms.")
    _table("Nameplates, structured OCR fields", counts)
    _table("Nameplates, raw OCR text next to the label", raw_counts)
    _table("Incident forms (employee codes and descriptions not compared)", form_counts)
    print("\nNameplate fields that disagree (structured field):")
    for tag, fields in sorted(wrong.items()):
        print(f"  {tag}: {', '.join(fields)}")
    print("Nameplate fields that also disagree in the raw OCR text:")
    for tag, fields in sorted(raw_wrong.items()):
        print(f"  {tag}: {', '.join(fields)}")
    print("Incident form fields that disagree:")
    for key, fields in sorted(form_wrong.items()):
        print(f"  {key}: {', '.join(fields)}")
    if not form_wrong:
        print("  none")
    print("\nFix via OCR Review (app tab): approve corrected values; the assistant then reads them as HUMAN-VERIFIED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
