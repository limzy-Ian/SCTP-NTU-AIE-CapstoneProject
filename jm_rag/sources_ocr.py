"""Loaders for processed OCR output, sensor summaries and audit files under data/processed."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from jm_rag import config
from jm_rag.common import _source
from jm_rag.config import PROCESSED_AUDITS


def _load_processed_audits() -> list[dict]:
    folder = config.ROOT / "data" / "processed"
    sources = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name not in PROCESSED_AUDITS:
            continue
        try:
            if path.suffix.lower() == ".json":
                content = json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=True)
            else:
                content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        sources.append(_source(
            path.name, "Derived audit artifact; source-specific and may lag live MySQL. " + content,
            path.relative_to(config.ROOT).as_posix(), source_type="processed_audit",
        ))
    return sources


def load_processed_ocr_sources(folder: Path | None = None) -> list[dict]:
    folder = folder or config.ROOT / "data" / "processed"
    sources = []
    nameplate_dir = folder / "nameplates"
    for path in sorted(nameplate_dir.glob("nameplate_*.json")):
        try:
            evidence = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        asset = evidence.get("asset") or {}
        filename = asset.get("source_file") or path.stem + ".jpg"
        tag = asset.get("asset_tag")
        sources.append(_source(
            f"{tag or filename} / processed nameplate OCR",
            "UNVERIFIED processed Tesseract OCR. Review flags: "
            + json.dumps(evidence.get("issues", []), default=str, ensure_ascii=True)
            + ". Extracted fields: " + json.dumps(asset, default=str, ensure_ascii=True),
            path.relative_to(config.ROOT).as_posix() if path.is_relative_to(config.ROOT) else path.as_posix(),
            asset_tag=tag, image=filename, image_folder="nameplates", source_type="processed_nameplate",
            confidence=evidence.get("ocr_confidence"),
        ))
        raw_path = path.with_suffix(".txt")
        if raw_path.is_file():
            try:
                raw_text = raw_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                continue
            sources.append(_source(
                f"{tag or filename} / raw processed OCR text", "UNVERIFIED raw OCR text: " + raw_text,
                raw_path.relative_to(config.ROOT).as_posix() if raw_path.is_relative_to(config.ROOT) else raw_path.as_posix(),
                asset_tag=tag, image=filename, image_folder="nameplates", source_type="processed_ocr_text",
            ))

    incident_dir = folder / "incident_reports"
    jsonl_path = incident_dir / "incident_reports_ocr_full.jsonl"
    if jsonl_path.is_file():
        try:
            incident_rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, UnicodeError, json.JSONDecodeError):
            incident_rows = []
        for row in incident_rows:
            filename = Path(row.get("image_path") or f"{row.get('report_no', '')}.jpg").name
            visible = {key: value for key, value in row.items()
                       if key not in {"emp_code", "image_path", "image_sha256", "ocr_raw_json"}}
            flags = row.get("extraction_flags", [])
            sources.append(_source(
                f"{row.get('report_no', filename)} / processed incident OCR",
                "UNVERIFIED processed incident OCR. Severity raw value, scale and normalized value "
                "are kept distinct. Review flags: " + json.dumps(flags, ensure_ascii=True)
                + ". Extracted fields: " + json.dumps(visible, default=str, ensure_ascii=True),
                jsonl_path.relative_to(config.ROOT).as_posix() if jsonl_path.is_relative_to(config.ROOT) else jsonl_path.as_posix(),
                asset_tag=row.get("machine_id"), image=filename,
                image_folder="incident_reports", record_key=row.get("report_no"),
                incident_date=row.get("incident_date"),
                record=visible,
                source_type="processed_incident",
                confidence=row.get("ocr_confidence"),
            ))

    sensor_dir = folder / "sensor"
    summary_path = sensor_dir / "sensor_summary.json"
    if summary_path.is_file():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            summary = {}
        for machine, values in (summary.get("sensors") or {}).items():
            readable = (
                f"Processed sensor summary for {machine}. Valid readings: {values.get('valid_readings')}; "
                f"expected between observed endpoints: {values.get('expected_between_first_last')}; "
                f"gap events: {values.get('gap_events')}; missing readings: {values.get('missing_readings')}; "
                f"completeness: {values.get('completeness_pct')}%; first UTC reading: "
                f"{values.get('first_reading_utc')}; last UTC reading: {values.get('last_reading_utc')}."
            )
            sources.append(_source(
                f"{machine} / processed sensor summary", readable + " "
                + json.dumps(values, default=str, ensure_ascii=True),
                summary_path.relative_to(config.ROOT).as_posix() if summary_path.is_relative_to(config.ROOT) else summary_path.as_posix(),
                asset_tag=machine, source_type="processed_sensor_summary",
            ))
        sources.append(_source(
            "Processed sensor dataset summary",
            "Processed sensor totals: " + json.dumps({key: value for key, value in summary.items() if key != "sensors"},
                                                       default=str, ensure_ascii=True),
            summary_path.relative_to(config.ROOT).as_posix() if summary_path.is_relative_to(config.ROOT) else summary_path.as_posix(),
            source_type="processed_sensor_summary",
        ))

    gaps_path = sensor_dir / "sensor_gaps.csv"
    if gaps_path.is_file():
        per_machine: dict[str, dict] = {}
        try:
            with gaps_path.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    machine = row.get("machine_id") or "UNKNOWN"
                    summary = per_machine.setdefault(machine, {"gap_events": 0, "missing_readings": 0,
                                                               "max_gap_minutes": 0.0, "examples": []})
                    summary["gap_events"] += 1
                    summary["missing_readings"] += int(row.get("missing_readings") or 0)
                    summary["max_gap_minutes"] = max(summary["max_gap_minutes"], float(row.get("gap_minutes") or 0))
                    if len(summary["examples"]) < 3:
                        summary["examples"].append({key: row.get(key) for key in
                                                     ("previous_timestamp_utc", "next_timestamp_utc", "gap_minutes")})
        except (OSError, UnicodeError, ValueError):
            per_machine = {}
        for machine, values in per_machine.items():
            sources.append(_source(
                f"{machine} / processed sensor gap summary",
                "Processed sensor_gaps.csv summary. Gaps are missing readings, not interpolated values. "
                + json.dumps(values, default=str, ensure_ascii=True),
                gaps_path.relative_to(config.ROOT).as_posix() if gaps_path.is_relative_to(config.ROOT) else gaps_path.as_posix(),
                asset_tag=machine, source_type="processed_sensor_gaps",
            ))
    return sources
