"""Offline EasyOCR/Tesseract comparison. Never connects to or writes to MySQL."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

import cv2
import numpy as np
import pytesseract
from dotenv import load_dotenv

if __package__:
    from . import ingest_incident_reports as incidents
    from . import nameplate_ocr_import as plates
else:
    import ingest_incident_reports as incidents
    import nameplate_ocr_import as plates

ROOT = Path(__file__).resolve().parents[1]
PLATE_FIELDS = [
    "plate_tag", "manufacturer", "model", "serial_number", "manufactured_ym",
    "power_kw", "electrical_spec", "fla_amps", "max_speed_rpm", "capacity_raw",
    "weight_kg", "lubricant", "grease_interval_hours",
]
INCIDENT_FIELDS = [
    "report_no_ocr", "incident_date", "machine_id", "emp_code", "description",
    "severity_label", "severity_raw", "severity_scale", "scale_source", "severity_5_worst",
    "lost_days", "reporting", "immediate_action", "root_cause_reference",
]
NUMERIC_FIELDS = {
    "power_kw", "fla_amps", "max_speed_rpm", "weight_kg", "grease_interval_hours",
    "severity_raw", "severity_5_worst", "lost_days",
}


def canonical(value, field: str) -> str:
    text = "" if value is None else str(value).strip()
    if field in NUMERIC_FIELDS and text:
        try:
            return str(Decimal(text).normalize())
        except InvalidOperation:
            pass
    return re.sub(r"\s+", " ", text).casefold()


def easy_data(results: list) -> dict:
    ordered = sorted(results, key=lambda result: (
        sum(point[1] for point in result[0]) / 4,
        min(point[0] for point in result[0]),
    ))
    rows = []
    for box, text, confidence in ordered:
        center = sum(point[1] for point in box) / 4
        height = max(point[1] for point in box) - min(point[1] for point in box)
        row = next((row for row in rows if abs(row["center"] - center)
                    <= max(4, min(row["height"], height) * 0.45)), None)
        if row is None:
            row = {"center": center, "height": height, "items": []}
            rows.append(row)
        row["items"].append((min(point[0] for point in box), str(text), float(confidence)))
    data = {key: [] for key in ("text", "conf", "page_num", "block_num", "par_num", "line_num")}
    for line, row in enumerate(sorted(rows, key=lambda row: row["center"]), 1):
        for _, text, confidence in sorted(row["items"]):
            data["text"].append(text)
            data["conf"].append(confidence * 100)
            for key in ("page_num", "block_num", "par_num"):
                data[key].append(1)
            data["line_num"].append(line)
    return data


def data_text(data: dict) -> tuple[str, float]:
    lines = {}
    for text, line in zip(data["text"], data["line_num"]):
        lines.setdefault(line, []).append(text)
    confidence = sum(data["conf"]) / len(data["conf"]) if data["conf"] else 0.0
    return "\n".join(" ".join(words) for words in lines.values()), round(confidence, 2)


class EasyAdapter:
    def __init__(self, reader):
        self.reader = reader

    def image_to_data(self, image, **kwargs):
        return easy_data(self.reader.readtext(image, detail=1, paragraph=False, workers=0))

    def image_to_string(self, image, **kwargs):
        return data_text(self.image_to_data(image))[0]

    def run_ocr(self, gray, *, psm=7, whitelist=""):
        if psm == 10:
            ys, xs = np.where(gray < 165)
            if len(xs):
                clipped = gray[max(0, int(ys.min()) - 3):int(ys.max()) + 4,
                               max(0, int(xs.min()) - 3):int(xs.max()) + 4]
                pad = max(12, clipped.shape[0] // 2)
                gray = cv2.copyMakeBorder(clipped, pad, pad, pad, pad,
                                          cv2.BORDER_CONSTANT, value=255)
        scale = 4 if psm == 10 else 3
        image = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        kwargs = {"detail": 1, "paragraph": False, "allowlist": whitelist or None, "workers": 0}
        if psm in (7, 10):
            results = self.reader.recognize(image, **kwargs)
        else:
            results = self.reader.readtext(image, **kwargs)
        text, _ = data_text(easy_data(results))
        weighted = [(float(result[2]) * 100, max(1, len(str(result[1])))) for result in results]
        confidence = sum(score * size for score, size in weighted) / sum(size for _, size in weighted) if weighted else 0
        return text, round(confidence, 2)


def extract(path: Path, kind: str, engine: str, adapter: EasyAdapter) -> dict:
    started = time.perf_counter()
    if kind == "nameplate":
        kwargs = {"data_reader": adapter.image_to_data, "text_reader": adapter.image_to_string} if engine == "easyocr" else {}
        raw, confidence, red, _ = plates.ocr_image(plates.read_image(path), **kwargs)
        values = plates.parse_nameplate(raw, red, path.name)
        flags = plates.flag_issues(values, confidence)
        evidence = {"text": raw, "red_text": red}
    else:
        kwargs = {"ocr_runner": adapter.run_ocr} if engine == "easyocr" else {}
        values = incidents.extract_one(path, **kwargs)
        readings = values["ocr_raw_json"]["readings"]
        match = incidents.REPORT_PATTERN.search(readings["report_no"])
        values["report_no_ocr"] = f"IR-{match.group(1)}-{int(match.group(2))}" if match else None
        values["severity_label"] = readings["severity_label"]
        confidence = values["ocr_confidence"]
        flags = values["extraction_flags"]
        evidence = values["ocr_raw_json"]
    return {"values": values, "confidence": confidence, "flags": flags, "evidence": evidence,
            "seconds": round(time.perf_counter() - started, 3), "error": ""}


def load_gold(path: Path | None) -> dict:
    if path is None:
        return {}
    gold = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"kind", "source_file", "field", "expected_value", "reviewed"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Ground truth must contain kind, source_file, field, expected_value, reviewed.")
        for row in reader:
            if row["reviewed"].strip().lower() not in ("yes", "true", "1"):
                continue
            key = (row["kind"], row["source_file"], row["field"])
            if key in gold:
                raise ValueError(f"Duplicate reviewed ground-truth field: {key}")
            gold[key] = row["expected_value"]
    return gold


def compare_field(kind, filename, field, pair, gold):
    left = pair["tesseract"]["values"].get(field)
    right = pair["easyocr"]["values"].get(field)
    first, second = canonical(left, field), canonical(right, field)
    if not first and not second:
        agreement = "BOTH_MISSING"
    elif not first or not second:
        agreement = "ONE_MISSING"
    else:
        agreement = "AGREE" if first == second else "DIFFER"
    key = (kind, filename, field)
    reviewed = key in gold
    expected = gold.get(key, "")
    return {"kind": kind, "source_file": filename, "field": field,
            "tesseract_value": left, "easyocr_value": right, "agreement": agreement,
            "expected_value": expected, "reviewed": "yes" if reviewed else "no",
            "tesseract_correct": int(not pair["tesseract"]["error"] and first == canonical(expected, field)) if reviewed else "",
            "easyocr_correct": int(not pair["easyocr"]["error"] and second == canonical(expected, field)) if reviewed else ""}


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_reports(results: list, output: Path, gold: dict, metadata: dict):
    field_rows, template, summary = [], [], []
    for kind, fields in (("nameplate", PLATE_FIELDS), ("incident", INCIDENT_FIELDS)):
        wide = []
        for result in results:
            if result["kind"] != kind:
                continue
            filename, pair = result["source_file"], result["engines"]
            row = {"source_file": filename}
            for engine, record in pair.items():
                row.update({f"{engine}_{field}": record["values"].get(field) for field in fields})
                row.update({f"{engine}_{field}": record[field] for field in ("confidence", "seconds", "error")})
                row[f"{engine}_flags"] = json.dumps(record["flags"], ensure_ascii=True)
            wide.append(row)
            for field in fields:
                field_rows.append(compare_field(kind, filename, field, pair, gold))
                template.append({"kind": kind, "source_file": filename, "field": field,
                                 "expected_value": "", "reviewed": "no"})
        columns = ["source_file"] + [f"{engine}_{field}" for engine in ("tesseract", "easyocr")
                                       for field in fields + ["confidence", "seconds", "flags", "error"]]
        write_csv(output / f"{kind}_comparison.csv", wide, columns)
        for engine in ("tesseract", "easyocr"):
            records = [result["engines"][engine] for result in results if result["kind"] == kind]
            scored = [row for row in field_rows if row["kind"] == kind and row["reviewed"] == "yes"]
            correct = sum(row[f"{engine}_correct"] for row in scored)
            summary.append({"kind": kind, "engine": engine, "images": len(records),
                            "errors": sum(bool(record["error"]) for record in records),
                            "extracted_fields": sum(bool(canonical(record["values"].get(field), field)) for record in records for field in fields),
                            "total_fields": len(records) * len(fields), "reviewed_fields": len(scored),
                            "correct_fields": correct if scored else "",
                            "accuracy_percent": round(100 * correct / len(scored), 2) if scored else "",
                            "total_seconds": round(sum(record["seconds"] for record in records), 3)})
    write_csv(output / "field_comparison.csv", field_rows,
              ["kind", "source_file", "field", "tesseract_value", "easyocr_value", "agreement",
               "expected_value", "reviewed", "tesseract_correct", "easyocr_correct"])
    write_csv(output / "engine_summary.csv", summary, list(summary[0]))
    template_path = output / "ground_truth_template.csv"
    if template_path.exists():
        with template_path.open(newline="", encoding="utf-8-sig") as handle:
            existing = list(csv.DictReader(handle))
        keys = {(row["kind"], row["source_file"], row["field"]) for row in existing}
        template = existing + [row for row in template if (row["kind"], row["source_file"], row["field"]) not in keys]
    write_csv(template_path, template, ["kind", "source_file", "field", "expected_value", "reviewed"])
    with (output / "raw_results.jsonl").open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, default=str, ensure_ascii=True) + "\n")
    (output / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    lines = ["# OCR engine comparison", "", "Offline only: no MySQL writes.", "",
             "Confidence scales are engine-specific, even though both are displayed as percentages.",
             "Review flags reuse existing importer heuristics; confidence thresholds are not calibrated for EasyOCR.",
             "Agreement and field completeness are not accuracy. Accuracy requires reviewed ground truth.",
             "Exact match ignores case/whitespace; numeric fields use decimal equivalence.",
             "Tags/report numbers are scored from image OCR, not filename fallback.", "",
             "| Kind | Engine | Images | Errors | Fields present | Reviewed | Accuracy | Seconds |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in summary:
        accuracy = str(row["accuracy_percent"]) + "%" if row["reviewed_fields"] else "Not scored"
        lines.append(f"| {row['kind']} | {row['engine']} | {row['images']} | {row['errors']} | "
                     f"{row['extracted_fields']}/{row['total_fields']} | {row['reviewed_fields']} | {accuracy} | {row['total_seconds']} |")
    lines += ["", f"EasyOCR model initialization/download: {metadata['easyocr_initialization_seconds']} seconds (excluded above).",
              "Timing includes image decoding, preprocessing and parsing, with fixed Tesseract-first order.",
              "CPU threading and first inference can affect timings; repeat runs before choosing an engine.",
              "", "Check side-by-side CSVs against source images. Fill expected_value and reviewed=yes in the ground-truth template.",
              "Keep missing/unreadable values honest. Review severity digits and printed scale independently.",
              "Re-run with --ground-truth pointing to your reviewed CSV to calculate field accuracy."]
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nameplates-dir", type=Path, default=ROOT / "data/images/nameplates")
    parser.add_argument("--incidents-dir", type=Path, default=ROOT / "data/images/incident_reports")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed/ocr_comparison")
    parser.add_argument("--limit", type=int, default=0, help="Images per category; 0 means all")
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--score-only", action="store_true", help="Score saved raw_results.jsonl without running OCR")
    parser.add_argument("--gpu", action="store_true", help="Use EasyOCR GPU instead of CPU")
    parser.add_argument("--cpu-threads", type=int, default=4)
    args = parser.parse_args()
    if args.limit < 0 or args.cpu_threads < 1:
        parser.error("--limit must be nonnegative and --cpu-threads must be positive")
    for folder in (args.nameplates_dir, args.incidents_dir):
        if not folder.is_dir():
            parser.error(f"Image directory not found: {folder}")
    gold = load_gold(args.ground_truth)
    if args.score_only:
        if args.ground_truth is None:
            parser.error("--score-only requires --ground-truth")
        raw_path = args.output / "raw_results.jsonl"
        if not raw_path.is_file():
            parser.error("No saved OCR results found. Run the comparison first.")
        results = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        metadata = json.loads((args.output / "run_metadata.json").read_text(encoding="utf-8"))
        metadata["ground_truth"] = str(args.ground_truth)
        write_reports(results, args.output, gold, metadata)
        print(f"Scored saved results against {len(gold)} reviewed ground-truth fields. No OCR or MySQL writes.")
        return 0
    load_dotenv(ROOT / ".env")
    executable = os.getenv("TESSERACT_CMD") or shutil.which("tesseract")
    if not executable and Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe").is_file():
        executable = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not executable:
        parser.error("Install Tesseract or set TESSERACT_CMD in .env.")
    pytesseract.pytesseract.tesseract_cmd = executable
    import easyocr
    import torch
    torch.set_num_threads(args.cpu_threads)
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    print("Loading EasyOCR English models (first run downloads model weights).", flush=True)
    reader = easyocr.Reader(["en"], gpu=args.gpu, model_storage_directory=str(args.output / "models"), verbose=False)
    initialization = round(time.perf_counter() - started, 3)
    adapter = EasyAdapter(reader)
    results, failures = [], 0
    for kind, folder in (("nameplate", args.nameplates_dir), ("incident", args.incidents_dir)):
        paths = sorted(path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg", ".png"))
        if args.limit:
            paths = paths[:args.limit]
        for path in paths:
            pair = {}
            for engine in ("tesseract", "easyocr"):
                started = time.perf_counter()
                try:
                    pair[engine] = extract(path, kind, engine, adapter)
                except Exception as error:
                    failures += 1
                    pair[engine] = {"values": {}, "flags": [], "evidence": {}, "confidence": None,
                                    "seconds": round(time.perf_counter() - started, 3),
                                    "error": f"{type(error).__name__}: {error}"}
                print(f"{kind} / {path.name} / {engine}: {pair[engine]['seconds']}s / "
                      f"{pair[engine]['error'] or 'processed'}", flush=True)
            results.append({"kind": kind, "source_file": path.name,
                            "source_path": str(path.resolve()), "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "engines": pair})
    if not results:
        parser.error("No JPEG/PNG images found.")
    metadata = {"easyocr_version": easyocr.__version__, "tesseract_version": str(pytesseract.get_tesseract_version()),
                "gpu": args.gpu, "cpu_threads": args.cpu_threads, "easyocr_initialization_seconds": initialization,
                "ground_truth": str(args.ground_truth) if args.ground_truth else None,
                "preprocessing": "Shared nameplate variants/red mask and incident ROIs/masks; common parsers."}
    write_reports(results, args.output, gold, metadata)
    print(f"Compared {len(results)} images. Tables: {args.output.resolve()}. No MySQL writes.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())