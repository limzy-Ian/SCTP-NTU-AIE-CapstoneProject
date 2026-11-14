"""Monthly sensor trend sources built from SQL month aggregates."""
from __future__ import annotations

import calendar
from datetime import date

from jm_rag.common import _source


def build_sensor_monthly_trend_sources(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["machine_id"], []).append(row)

    sources = []
    for machine_id, monthly_rows in grouped.items():
        monthly_rows.sort(key=lambda row: str(row["month_utc"]))
        lines = [
            f"Monthly sensor trend for machine {machine_id}, computed from observed MySQL sensor_readings. "
            "Vibration is RMS in mm/s; temperature is normalized to Celsius. These are descriptive statistics, "
            "not a fault diagnosis or threshold alert."
        ]
        previous = None
        for row in monthly_rows:
            month_start = date.fromisoformat(str(row["month_utc"])[:10])
            days = calendar.monthrange(month_start.year, month_start.month)[1]
            expected_readings = days * (24 * 60 // 12)
            completeness = 100 * int(row["reading_count"]) / expected_readings
            line = (
                f"{month_start:%Y-%m}: {row['reading_count']} observed readings "
                f"({completeness:.1f}% of expected 12-minute readings); "
                f"mean vibration {float(row['vibration_mean_mms']):.3f} mm/s, "
                f"maximum vibration {float(row['vibration_max_mms']):.3f} mm/s; "
                f"mean temperature {float(row['temperature_mean_c']):.2f} C, "
                f"maximum temperature {float(row['temperature_max_c']):.2f} C."
            )
            if previous is not None and completeness >= 50 and previous["completeness"] >= 50:
                prior = previous["row"]
                vibration_change = float(row["vibration_mean_mms"]) - float(prior["vibration_mean_mms"])
                temperature_change = float(row["temperature_mean_c"]) - float(prior["temperature_mean_c"])
                vibration_pct = (100 * vibration_change / float(prior["vibration_mean_mms"])
                                 if float(prior["vibration_mean_mms"]) else None)
                temperature_pct = (100 * temperature_change / float(prior["temperature_mean_c"])
                                   if float(prior["temperature_mean_c"]) else None)
                line += (f" Month-over-month change from {previous['month']}: "
                         f"vibration {vibration_change:+.3f} mm/s"
                         + (f" ({vibration_pct:+.1f}%)" if vibration_pct is not None else "")
                         + f"; temperature {temperature_change:+.2f} C"
                         + (f" ({temperature_pct:+.1f}%)" if temperature_pct is not None else "") + ".")
            elif completeness < 50:
                line += " Partial-month coverage is too low for a month-over-month comparison."
            lines.append(line)
            previous = {"month": f"{month_start:%Y-%m}", "row": row, "completeness": completeness}
        sources.append(_source(
            f"{machine_id} / monthly sensor trends",
            "\n".join(lines),
            "MySQL: sensor_readings, grouped by UTC calendar month; expected cadence 12 minutes",
            asset_tag=machine_id, source_type="sensor_trend_monthly",
        ))
    return sources


SHIFT_NOTE = ("Shift hours are assumed: day 07:00-18:59 and night 19:00-06:59 Singapore time; the CMMS does not record "
              "shift times.")


def build_sensor_shift_sources(rows: list[dict]) -> list[dict]:
    """One source per machine: monthly mean vibration and temperature for the day and the night shift."""
    grouped: dict[str, dict[str, dict[str, dict]]] = {}
    for row in rows:
        grouped.setdefault(row["machine_id"], {}).setdefault(str(row["month_utc"])[:7], {})[row["shift"]] = row
    sources = []
    for machine_id, months in grouped.items():
        lines = [f"Day and night shift sensor means for machine {machine_id}, by UTC month, from MySQL sensor_readings. "
                 f"{SHIFT_NOTE} Descriptive statistics, not a diagnosis."]
        for month in sorted(months):
            parts = []
            for shift in ("day", "night"):
                row = months[month].get(shift)
                if row:
                    parts.append(f"{shift} mean vibration {float(row['vibration_mean_mms']):.3f} mm/s, mean temperature "
                                 f"{float(row['temperature_mean_c']):.2f} C ({row['reading_count']} readings)")
            lines.append(f"{month}: " + "; ".join(parts) + ".")
        sources.append(_source(f"{machine_id} / sensor by shift", "\n".join(lines),
                               "MySQL: sensor_readings, grouped by UTC month and assumed shift", asset_tag=machine_id,
                               source_type="sensor_shift_monthly"))
    return sources
