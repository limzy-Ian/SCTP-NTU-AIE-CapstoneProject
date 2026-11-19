"""Human review decisions for OCR staging; source OCR rows remain unchanged."""
from __future__ import annotations

import json

import mysql.connector

REVIEW_DDL = """CREATE TABLE IF NOT EXISTS ocr_review_decisions (
  record_type VARCHAR(24) NOT NULL,
  record_key VARCHAR(512) NOT NULL,
  review_status VARCHAR(24) NOT NULL,
  reviewer VARCHAR(100) NOT NULL,
  notes TEXT NULL,
  corrections JSON NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (record_type, record_key),
  KEY idx_ocr_review_status (review_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


def open_connection():
    import os
    from jm_rag import config

    env_path = config.ROOT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3307")),
        database=os.getenv("MYSQL_DATABASE", "jurong_marine"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        connection_timeout=5,
    )

def ensure_review_table(connection):
    cursor = connection.cursor()
    try:
        cursor.execute(REVIEW_DDL)
        connection.commit()
    finally:
        cursor.close()


def review_decision(cursor, record_type: str, record_key: str) -> dict:
    cursor.execute(
        "SELECT review_status, reviewer, notes, corrections, updated_at "
        "FROM ocr_review_decisions WHERE record_type=%s AND record_key=%s",
        (record_type, record_key),
    )
    row = cursor.fetchone()
    if not row:
        return {"review_status": "PENDING_REVIEW", "reviewer": None,
                "notes": None, "corrections": {}, "updated_at": None}
    corrections = row["corrections"] if isinstance(row["corrections"], dict) else json.loads(row["corrections"] or "{}")
    return {**row, "corrections": corrections}


def list_reviews(connection, record_type: str, status: str = "All") -> list[dict]:
    cursor = connection.cursor(dictionary=True)
    try:
        if record_type == "nameplate":
            cursor.execute("""SELECT r.source_key AS record_key, r.source_file,
                r.ocr_text AS raw_text, r.ocr_confidence AS confidence,
                s.asset_tag, s.category, s.manufacturer, s.model, s.serial_number,
                s.manufactured_ym, s.power_kw, s.electrical_spec, s.fla_amps,
                s.max_speed_rpm, s.capacity_raw, s.weight_kg, s.lubricant,
                s.grease_interval_hours, s.flags_json AS flags
                FROM nameplate_ocr_raw r JOIN nameplate_assets_staging s ON s.raw_id=r.id
                ORDER BY s.asset_tag""")
            image_folder = "nameplates"
        else:
            cursor.execute("""SELECT report_no AS record_key, report_no AS source_file,
                image_path, ocr_raw_json AS raw_text, ocr_confidence AS confidence,
                incident_date, machine_id, location_raw, emp_code, description,
                severity_raw, severity_scale, scale_source, severity_5_worst,
                lost_days, reporting, immediate_action, root_cause_reference,
                extraction_flags AS flags
                FROM incident_report_ocr ORDER BY incident_date, report_no""")
            image_folder = "incident_reports"
        rows = cursor.fetchall()
        reviewed = []
        for row in rows:
            decision = review_decision(cursor, record_type, row["record_key"])
            row.update(decision)
            row["image_folder"] = image_folder
            reviewed.append(row)
        if status != "All":
            reviewed = [row for row in reviewed if row["review_status"] == status]
        return reviewed
    finally:
        cursor.close()


def save_review(connection, record_type: str, record_key: str, status: str,
                reviewer: str, notes: str, corrections: dict) -> None:
    if status not in {"APPROVED", "REJECTED", "PENDING_REVIEW"}:
        raise ValueError("Invalid review status")
    if not reviewer.strip():
        raise ValueError("Reviewer is required")
    cursor = connection.cursor()
    try:
        cursor.execute("""INSERT INTO ocr_review_decisions
            (record_type, record_key, review_status, reviewer, notes, corrections)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE review_status=VALUES(review_status),
            reviewer=VALUES(reviewer), notes=VALUES(notes), corrections=VALUES(corrections)""",
            (record_type, record_key, status, reviewer.strip(), notes.strip() or None,
             json.dumps(corrections, ensure_ascii=True)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def effective_record(record: dict) -> tuple[dict, str]:
    values = {key: value for key, value in record.items()
              if key not in {"corrections", "review_status", "reviewer", "notes", "updated_at"}}
    corrections = record.get("corrections") or {}
    if isinstance(corrections, str):
        corrections = json.loads(corrections)
    if record.get("review_status") == "APPROVED":
        values.update(corrections)
        return values, "HUMAN-VERIFIED"
    return values, "UNVERIFIED OCR"