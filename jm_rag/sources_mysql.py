"""Loaders that read the CMMS, OCR staging and sensor tables from MySQL (read-only)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import mysql.connector

from jm_rag.common import _source
from jm_rag.config import ASSET_PATTERN
from jm_rag.sensors import build_sensor_monthly_trend_sources, build_sensor_shift_sources
from scripts.ocr_review import effective_record, ensure_review_table, open_connection


def _query_rows(cursor, query: str, label: str, warnings: list[str]) -> list[dict]:
    try:
        cursor.execute(query)
        return cursor.fetchall()
    except mysql.connector.Error as error:
        warnings.append(f"MySQL source {label} unavailable: {error}")
        return []


def _query_one(cursor, query: str, label: str, warnings: list[str]) -> dict | None:
    try:
        cursor.execute(query)
        return cursor.fetchone()
    except mysql.connector.Error as error:
        warnings.append(f"MySQL source {label} unavailable: {error}")
        return None


def _load_mysql_sources(sources: list[dict], warnings: list[str]) -> set[str]:
    connection = None
    image_names: set[str] = set()
    try:
        connection = open_connection()
        ensure_review_table(connection)
        cursor = connection.cursor(dictionary=True)
        try:
            nameplate_rows = _query_rows(cursor, """SELECT s.asset_tag, s.category, s.manufacturer, s.model,
                s.serial_number, s.manufactured_ym, s.power_kw, s.electrical_spec,
                s.fla_amps, s.max_speed_rpm, s.capacity_raw, s.weight_kg,
                s.lubricant, s.grease_interval_hours, s.needs_review,
                s.flags_json, r.source_file, r.ocr_confidence,
                m.machine_name, m.model AS cmms_model, r.source_key AS record_key,
                d.review_status, d.notes, d.corrections
                FROM nameplate_assets_staging s
                JOIN nameplate_ocr_raw r ON r.id = s.raw_id
                LEFT JOIN machines m ON m.machine_id = s.asset_tag
                LEFT JOIN ocr_review_decisions d ON d.record_type='nameplate' AND d.record_key=r.source_key
                ORDER BY s.asset_tag""", "nameplate staging", warnings)
            for database_row in nameplate_rows:
                row, trust = effective_record(database_row)
                row.pop("reviewer", None)  # reviewer identity is personal data; never put it in evidence
                row["evidence_status"] = trust
                image_names.add(row["source_file"])
                filename_match = ASSET_PATTERN.search(Path(row["source_file"]).stem.replace("_", " ").upper())
                filename_tag = filename_match.group(0) if filename_match else None
                source_tags = {row["asset_tag"].upper()} if row["asset_tag"] else set()
                if filename_tag:
                    source_tags.add(filename_tag.upper())
                if filename_tag and row["asset_tag"] and filename_tag.upper() != row["asset_tag"].upper():
                    row["review_conflict"] = (
                        f"Filename tag {filename_tag} conflicts with approved database tag {row['asset_tag']}; "
                        "do not rely on this record until the source image is reviewed again."
                    )
                sources.append(_source(
                    f"{filename_tag or row['asset_tag']} / {row['source_file']}",
                    f"{trust}; CMMS model is a separate source. " + json.dumps(row, default=str, ensure_ascii=True),
                    "MySQL: nameplate_assets_staging + nameplate_ocr_raw + machines",
                    asset_tag=filename_tag or row["asset_tag"], asset_tags=sorted(source_tags),
                    image=row["source_file"],
                    image_folder="nameplates", source_type="nameplate",
                ))

            for row in _query_rows(cursor, "SELECT machine_id, machine_name, model, year_installed FROM machines ORDER BY machine_id",
                                   "machines", warnings):
                aliases = [value for value in (
                    row["machine_id"], row["machine_name"], row["model"],
                    str(row["model"]).split()[-1] if row.get("model") else None,
                ) if value]
                sources.append(_source(
                    f"{row['machine_id']} / machine master",
                    "CMMS machine master record. " + json.dumps(row, default=str, ensure_ascii=True),
                    "MySQL: machines", asset_tag=row["machine_id"], asset_aliases=aliases,
                    machine_record=True, source_type="mysql",
                ))

            for row in _query_rows(cursor, """SELECT wo_id, machine_id, wo_type, description, wo_date,
                duration_hrs, cost_sgd, status FROM work_orders ORDER BY wo_date DESC""",
                                   "work orders", warnings):
                sources.append(_source(
                    f"Work order {row['wo_id']} / {row['machine_id']}",
                    "CMMS work order. " + json.dumps(row, default=str, ensure_ascii=True),
                    "MySQL: work_orders", asset_tag=row["machine_id"],
                    record_date=row["wo_date"], record=row, source_type="work_order",
                ))

            for row in _query_rows(cursor, """SELECT incident_id, incident_date, machine_id, description,
                severity, lost_days, reporting FROM safety_incidents ORDER BY incident_date DESC""",
                                   "CMMS incidents", warnings):
                incident_date = row["incident_date"]
                if incident_date:
                    old_scale = incident_date < date(2025, 7, 1)
                    severity_scale = "OLD_1_WORST" if old_scale else "NEW_5_WORST"
                    severity_5_worst = 6 - row["severity"] if old_scale and row["severity"] else row["severity"]
                else:
                    severity_scale, severity_5_worst = "UNKNOWN", None
                record = {**row, "severity_raw": row["severity"], "severity_scale": severity_scale,
                          "severity_5_worst": severity_5_worst}
                record.pop("severity", None)
                sources.append(_source(
                    f"Incident {row['incident_id']} / {row['machine_id']}",
                    "CMMS incident. Severity is normalized only using the documented date cutoff; "
                    "record-level image is not attached. " + json.dumps(record, default=str, ensure_ascii=True),
                    "MySQL: safety_incidents", asset_tag=row["machine_id"],
                    incident_id=str(row["incident_id"]), incident_date=incident_date,
                    record=record, source_type="incident",
                ))

            for database_row in _query_rows(cursor, """SELECT o.report_no AS record_key, o.incident_date, o.machine_id,
                o.location_raw, o.description, o.severity_raw, o.severity_scale,
                o.scale_source, o.severity_5_worst, o.lost_days, o.reporting,
                o.immediate_action, o.root_cause_reference, o.image_path,
                o.ocr_confidence, o.extraction_flags, o.ocr_raw_json,
                o.review_status AS ingest_status, d.review_status,
                d.notes, d.corrections
                FROM incident_report_ocr o LEFT JOIN ocr_review_decisions d
                ON d.record_type='incident' AND d.record_key=o.report_no
                ORDER BY o.incident_date DESC""", "incident OCR staging", warnings):
                row, trust = effective_record(database_row)
                row.pop("reviewer", None)  # reviewer identity is personal data; never put it in evidence
                filename = Path(row["image_path"]).name
                image_names.add(filename)
                review_flags = row.get("extraction_flags")
                if isinstance(review_flags, str):
                    try:
                        review_flags = json.loads(review_flags)
                    except json.JSONDecodeError:
                        pass
                row["evidence_status"] = trust
                row["image_file"] = filename
                row.pop("ocr_raw_json", None)
                row.pop("image_path", None)
                row.pop("emp_code", None)
                sources.append(_source(
                    f"{row['record_key']} / incident report image",
                    f"{trust}; OCR extraction flags={review_flags}. "
                    + json.dumps(row, default=str, ensure_ascii=True),
                    "MySQL: incident_report_ocr + ocr_review_decisions",
                    asset_tag=row.get("machine_id"), image=filename,
                    image_folder="incident_reports", record_key=row["record_key"],
                    incident_date=row.get("incident_date"),
                    record=row,
                    source_type="incident_ocr",
                ))

            sensor_rows = _query_rows(cursor, """SELECT machine_id, COUNT(*) AS reading_count,
                MIN(timestamp_utc) AS first_reading_utc, MAX(timestamp_utc) AS last_reading_utc,
                AVG(vib_rms_mms) AS vibration_avg_mms, MAX(vib_rms_mms) AS vibration_max_mms,
                AVG(temperature_c) AS temperature_avg_c, MAX(temperature_c) AS temperature_max_c
                FROM sensor_readings GROUP BY machine_id ORDER BY machine_id""", "sensor readings", warnings)
            gap_rows_result = _query_rows(cursor, """SELECT machine_id, COUNT(*) AS gap_events,
                SUM(missing_readings) AS missing_readings, MAX(gap_minutes) AS max_gap_minutes
                FROM sensor_gaps GROUP BY machine_id ORDER BY machine_id""", "sensor gaps", warnings)
            gap_rows = {row["machine_id"]: row for row in gap_rows_result}
            for row in sensor_rows:
                sensor = {**row, **gap_rows.get(row["machine_id"], {})}
                sensor_text = (
                    f"Machine {row['machine_id']} sensor time-series aggregate. "
                    f"Readings: {sensor['reading_count']}. First UTC reading: {sensor['first_reading_utc']}; "
                    f"last UTC reading: {sensor['last_reading_utc']}. "
                    f"Average vibration RMS: {sensor['vibration_avg_mms']} mm/s; "
                    f"maximum vibration RMS: {sensor['vibration_max_mms']} mm/s. "
                    f"Average temperature: {sensor['temperature_avg_c']} C; "
                    f"maximum temperature: {sensor['temperature_max_c']} C. "
                    f"Sensor gaps: {sensor.get('gap_events', 0)} events; "
                    f"{sensor.get('missing_readings', 0)} missing readings; "
                    f"maximum gap {sensor.get('max_gap_minutes', 0)} minutes. "
                    "These descriptive statistics are not diagnoses; no safety thresholds are provided. "
                    + json.dumps(sensor, default=str, ensure_ascii=True)
                )
                sources.append(_source(
                    f"{row['machine_id']} / sensor summary",
                    "SQL aggregates computed from sensor_readings. Temperatures are normalized to Celsius; "
                    "original values remain in SQL. " + sensor_text,
                    "MySQL: sensor_readings + sensor_gaps; source CSV: data/logs/vibration_temp_2026H1.csv",
                    asset_tag=row["machine_id"], source_type="sensor_summary",
                ))
            monthly_sensor_rows = _query_rows(cursor, """SELECT machine_id,
                DATE_FORMAT(timestamp_utc, '%Y-%m-01') AS month_utc, COUNT(*) AS reading_count,
                AVG(vib_rms_mms) AS vibration_mean_mms, MAX(vib_rms_mms) AS vibration_max_mms,
                AVG(temperature_c) AS temperature_mean_c, MAX(temperature_c) AS temperature_max_c
                FROM sensor_readings
                GROUP BY machine_id, DATE_FORMAT(timestamp_utc, '%Y-%m-01')
                ORDER BY machine_id, month_utc""",
                "monthly sensor trends", warnings)
            sources.extend(build_sensor_monthly_trend_sources(monthly_sensor_rows))
            # Day and night by month. Shift hours are an assumption: day 07:00-18:59, night 19:00-06:59, Singapore time
            # (UTC+8). The CMMS does not record shift times.
            shift_rows = _query_rows(cursor, """SELECT machine_id, DATE_FORMAT(timestamp_utc, '%Y-%m') AS month_utc,
                CASE WHEN HOUR(DATE_ADD(timestamp_utc, INTERVAL 8 HOUR)) BETWEEN 7 AND 18 THEN 'day' ELSE 'night' END AS shift,
                COUNT(*) AS reading_count, AVG(vib_rms_mms) AS vibration_mean_mms, AVG(temperature_c) AS temperature_mean_c
                FROM sensor_readings GROUP BY machine_id, month_utc, shift ORDER BY machine_id, month_utc, shift""",
                "sensor readings by shift", warnings)
            sources.extend(build_sensor_shift_sources(shift_rows))
            issues = _query_rows(cursor, """SELECT issue_code, COUNT(*) AS issue_count
                FROM sensor_quality_issues GROUP BY issue_code ORDER BY issue_code""", "sensor quality issues", warnings)
            if issues:
                sources.append(_source("Sensor data quality issues",
                    "SQL count by issue code: " + json.dumps(issues, default=str, ensure_ascii=True),
                    "MySQL: sensor_quality_issues", source_type="mysql"))

            summary = _query_one(cursor, "SELECT COUNT(*) AS total, MIN(wo_date) AS first_date, MAX(wo_date) AS last_date FROM work_orders",
                                 "work order coverage", warnings)
            if summary:
                sources.append(_source("CMMS work order coverage", json.dumps(summary, default=str),
                                       "MySQL: work_orders", source_type="mysql_summary"))
            # Possible duplicate people: codes that share a full name. Only the codes leave the database; the
            # name is used inside the query to group and is never selected.
            duplicates = _query_rows(cursor, """SELECT GROUP_CONCAT(emp_code ORDER BY emp_code SEPARATOR ', ') AS codes
                FROM employees GROUP BY LOWER(TRIM(emp_name)) HAVING COUNT(*) > 1""", "employee data quality", warnings)
            if duplicates is not None:
                groups = [row["codes"] for row in duplicates if row.get("codes")]
                sources.append(_source(
                    "Employee data quality (codes only)",
                    f"Employee codes that share the same full name in the employees table (a possible duplicate person; "
                    f"names withheld): {len(groups)} group(s)" + (": " + "; ".join(groups) if groups else "") + ". "
                    "A shared name does not prove that two codes are the same person.",
                    "MySQL: employees (codes only)", source_type="employee_data_quality"))
        finally:
            cursor.close()
    except (mysql.connector.Error, ValueError, OSError) as error:
        warnings.append(f"MySQL connection or review setup failed: {error}")
    finally:
        if connection is not None:
            connection.close()
    return image_names
