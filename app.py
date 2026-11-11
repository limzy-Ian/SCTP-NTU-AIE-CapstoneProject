"""Streamlit entry point for the read-only maintenance RAG prototype."""
import json
import os
import re
import time
import calendar
import math
from datetime import datetime, time as datetime_time, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from scripts.maintenance_rag import (
    ASSET_PATTERN, ROOT, format_combined_history_table, format_incident_table,
    format_work_order_table, input_refusal, is_history_table_request,
    is_work_order_table_request, load_sources, load_system_prompt,
    partial_work_order_date, resolve_partial_work_order_date, retrieve,
    serialize_evidence, validate_answer,
)
from scripts.chat_history import (
    append_chat_turn, create_chat, delete_chat, ensure_chat_schema,
    list_chats, load_chat_messages,
)
from scripts.ocr_review import ensure_review_table, list_reviews, open_connection, save_review


def api_cost_rates(model):
    input_rate = os.getenv("OPENAI_INPUT_COST_PER_1M_USD")
    output_rate = os.getenv("OPENAI_OUTPUT_COST_PER_1M_USD")
    if input_rate is not None or output_rate is not None:
        if input_rate is None or output_rate is None:
            return None
        try:
            rates = float(input_rate), float(output_rate)
        except ValueError:
            return None
        return rates if all(math.isfinite(rate) and rate >= 0 for rate in rates) else None
    if not os.getenv("OPENAI_BASE_URL") and model == "gpt-4o-mini":
        return 0.15, 0.60
    return None


def estimate_api_cost(usage, model):
    rates = api_cost_rates(model)
    if usage is None or rates is None:
        return None
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1_000_000


def show_evidence(sources):
    for source in sources:
        with st.expander(f"[{source['id']}] {source['title']}"):
            st.caption(source["location"])
            st.text(source["text"])
            filename = source.get("image")
            if filename and filename == os.path.basename(filename):
                image_folder = source.get("image_folder", "nameplates")
                image = ROOT / "data" / "images" / image_folder / filename
                if image.is_file():
                    st.image(str(image))


def render_review():
    st.subheader("OCR review queue")
    st.caption("Review source images and OCR before records are trusted. Decisions are stored separately from source OCR and CMMS records.")
    reviewer = st.text_input("Reviewer", value=os.getenv("OCR_REVIEWER", ""), key="ocr_reviewer")
    kind_label = st.radio("Record type", ["Nameplates", "Incident reports"], horizontal=True)
    record_type = "nameplate" if kind_label == "Nameplates" else "incident"
    status_filter = st.selectbox("Review status", ["PENDING_REVIEW", "All", "APPROVED", "REJECTED"], index=0)
    connection = None
    try:
        connection = open_connection()
        ensure_review_table(connection)
        records = list_reviews(connection, record_type, status_filter)
    except Exception as error:
        st.error(f"Cannot load the OCR review queue: {error}")
        return
    finally:
        if connection is not None:
            connection.close()
    pending_count = sum(row["review_status"] == "PENDING_REVIEW" for row in records)
    st.metric("Records in this view", len(records), delta=f"{pending_count} pending")
    if not records:
        st.info("No records match this filter.")
        return
    labels = [f"{row['record_key']} | {row['review_status']}" for row in records]
    selected = st.selectbox("Record", range(len(records)), format_func=lambda index: labels[index])
    record = records[selected]
    left, right = st.columns([1, 1])
    image_name = os.path.basename(record.get("image_path") or record.get("source_file", ""))
    image_path = ROOT / "data" / "images" / record["image_folder"] / image_name
    filename_match = ASSET_PATTERN.search(Path(image_name).stem.replace("_", " ").upper())
    filename_tag = filename_match.group(0) if filename_match else None
    corrections = record.get("corrections") or {}
    reviewed_tag = corrections.get("asset_tag", record.get("asset_tag"))
    if record_type == "nameplate" and filename_tag and reviewed_tag != filename_tag:
        st.error(f"Source mismatch: filename tag is {filename_tag}, but the staged/reviewed tag is {reviewed_tag}. Recheck this image before approval.")
    with left:
        st.markdown("**Source image**")
        if image_path.is_file():
            st.image(str(image_path), width="stretch")
        else:
            st.warning(f"Image file not found: {image_name}")
        with st.expander("Original OCR evidence"):
            raw = record.get("raw_text")
            if isinstance(raw, (dict, list)):
                st.json(raw)
            else:
                st.text(str(raw or "No raw OCR evidence stored."))
    fields = (["asset_tag", "category", "manufacturer", "model", "serial_number",
               "manufactured_ym", "power_kw", "electrical_spec", "fla_amps",
               "max_speed_rpm", "capacity_raw", "weight_kg", "lubricant",
               "grease_interval_hours"] if record_type == "nameplate" else
              ["incident_date", "machine_id", "location_raw", "emp_code", "description",
               "severity_raw", "severity_scale", "scale_source", "severity_5_worst",
               "lost_days", "reporting", "immediate_action", "root_cause_reference"])
    values = {field: record.get(field) for field in fields}
    if record["review_status"] == "APPROVED":
        values.update(corrections)
    try:
        flags = record.get("flags") or []
        if isinstance(flags, str):
            flags = json.loads(flags)
    except (TypeError, json.JSONDecodeError):
        flags = ["Could not parse stored review flags"]
    with right:
        st.markdown("**Extracted fields**")
        st.json(values)
        st.caption(f"OCR confidence: {record.get('confidence')}% | Current status: {record['review_status']}")
        if record["review_status"] == "APPROVED" and corrections:
            st.caption("Approved human corrections are shown above; original OCR is preserved separately.")
        st.markdown("**Quality flags**")
        st.json(flags)
        if record.get("reviewer"):
            st.caption(f"Last reviewed by {record['reviewer']} at {record.get('updated_at')}")
        review_widget_key = f"{record_type}_{record['record_key']}"
        with st.form(f"save_ocr_review_{review_widget_key}"):
            decision = st.selectbox("Decision", ["APPROVED", "REJECTED", "PENDING_REVIEW"],
                                    index={"APPROVED": 0, "REJECTED": 1, "PENDING_REVIEW": 2}.get(record["review_status"], 2),
                                    key=f"decision_{review_widget_key}")
            corrections_text = st.text_area(
                "Corrected fields (JSON)",
                value=json.dumps(corrections, indent=2, ensure_ascii=True),
                height=180,
                help="Only enter corrected field values, for example {\"model\": \"Verified model\"}.",
                key=f"corrections_{review_widget_key}",
            )
            notes = st.text_area("Review notes", value=record.get("notes") or "", height=90,
                                 key=f"notes_{review_widget_key}")
            submitted = st.form_submit_button("Save review", icon=":material/save:",
                                              key=f"submit_{review_widget_key}")
        if submitted:
            if not reviewer.strip():
                st.error("Enter a reviewer name or initials before saving.")
            else:
                try:
                    corrections = json.loads(corrections_text or "{}")
                    if not isinstance(corrections, dict):
                        raise ValueError("Corrected fields must be a JSON object.")
                    unknown = set(corrections) - set(fields)
                    if unknown:
                        raise ValueError("Unknown correction fields: " + ", ".join(sorted(unknown)))
                    connection = open_connection()
                    try:
                        ensure_review_table(connection)
                        save_review(connection, record_type, record["record_key"], decision,
                                    reviewer, notes, corrections)
                    finally:
                        connection.close()
                    st.success("Review saved. Source OCR remains unchanged.")
                    st.rerun()
                except (ValueError, json.JSONDecodeError) as error:
                    st.error(str(error))
                except Exception as error:
                    st.error(f"Could not save review: {error}")


def render_sensor_trends():
    st.subheader("Sensor trends")
    st.caption("Hourly summaries from MySQL sensor_readings. Temperature is normalized to Celsius; timestamps are UTC.")
    connection = None
    try:
        connection = open_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT DISTINCT machine_id FROM sensor_readings ORDER BY machine_id")
        machines = [row["machine_id"] for row in cursor.fetchall()]
        cursor.execute("SELECT MIN(timestamp_utc) AS first_reading, MAX(timestamp_utc) AS last_reading FROM sensor_readings")
        coverage = cursor.fetchone()
        cursor.close()
    except Exception as error:
        st.error(f"Cannot load sensor data from MySQL: {error}")
        return
    finally:
        if connection is not None:
            connection.close()
    if not machines or not coverage or coverage["first_reading"] is None:
        st.info("No sensor readings are loaded in MySQL.")
        return

    first_day = coverage["first_reading"].date()
    last_day = coverage["last_reading"].date()
    filters = st.columns([2, 2, 1])
    with filters[0]:
        selected_machines = st.multiselect("Machines", machines, default=machines)
    with filters[1]:
        selected_dates = st.date_input(
            "Date range (UTC)", value=(first_day, last_day),
            min_value=first_day, max_value=last_day,
        )
    with filters[2]:
        statistic = st.selectbox("Hourly statistic", ["Mean", "Maximum"])
    if not selected_machines:
        st.info("Select at least one machine.")
        return
    if not isinstance(selected_dates, (tuple, list)) or len(selected_dates) != 2:
        st.info("Select both a start and end date.")
        return
    start_date, end_date = selected_dates
    if end_date < start_date:
        st.error("The end date must be on or after the start date.")
        return

    start_utc = datetime.combine(start_date, datetime_time.min)
    end_utc = datetime.combine(end_date + timedelta(days=1), datetime_time.min)
    machine_placeholders = ",".join(["%s"] * len(selected_machines))
    reading_sql = f"""SELECT machine_id,
        TIMESTAMP(DATE(timestamp_utc), MAKETIME(HOUR(timestamp_utc), 0, 0)) AS hour_utc,
        COUNT(*) AS reading_count,
        AVG(vib_rms_mms) AS vibration_mean_mms, MAX(vib_rms_mms) AS vibration_max_mms,
        AVG(temperature_c) AS temperature_mean_c, MAX(temperature_c) AS temperature_max_c
        FROM sensor_readings
        WHERE timestamp_utc >= %s AND timestamp_utc < %s
          AND machine_id IN ({machine_placeholders})
        GROUP BY machine_id, hour_utc ORDER BY hour_utc, machine_id"""
    gaps_sql = f"""SELECT machine_id, COUNT(*) AS gap_events,
        SUM(missing_readings) AS missing_readings, MAX(gap_minutes) AS max_gap_minutes
        FROM sensor_gaps
        WHERE next_timestamp_utc > %s AND previous_timestamp_utc < %s
          AND machine_id IN ({machine_placeholders})
        GROUP BY machine_id ORDER BY machine_id"""
    connection = None
    try:
        connection = open_connection()
        cursor = connection.cursor(dictionary=True)
        parameters = (start_utc, end_utc, *selected_machines)
        cursor.execute(reading_sql, parameters)
        readings = cursor.fetchall()
        cursor.execute(gaps_sql, parameters)
        gaps = cursor.fetchall()
    except Exception as error:
        st.error(f"Cannot query sensor readings: {error}")
        return
    finally:
        if connection is not None:
            connection.close()
    if not readings:
        st.info("No readings match the selected machines and date range.")
        return

    frame = pd.DataFrame(readings)
    frame["hour_utc"] = pd.to_datetime(frame["hour_utc"], utc=True)
    for column in ("vibration_mean_mms", "vibration_max_mms", "temperature_mean_c", "temperature_max_c"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    gap_events = sum(int(row["gap_events"] or 0) for row in gaps)
    missing_readings = sum(int(row["missing_readings"] or 0) for row in gaps)
    max_gap = max((float(row["max_gap_minutes"] or 0) for row in gaps), default=0)
    metrics = st.columns(3)
    metrics[0].metric("Readings", f"{int(frame['reading_count'].sum()):,}")
    metrics[1].metric("Gap events", f"{gap_events:,}", delta=f"{missing_readings:,} missing readings")
    metrics[2].metric("Longest gap", f"{max_gap:g} min")
    if missing_readings:
        st.warning("Missing readings are not interpolated. Hourly values summarize observed readings only.")

    suffix = "mean" if statistic == "Mean" else "max"
    st.caption(f"Showing hourly {statistic.lower()} across {frame['hour_utc'].nunique():,} time buckets. Source: MySQL sensor_readings and sensor_gaps.")
    st.markdown("**Vibration RMS (mm/s)**")
    vibration = frame.pivot(index="hour_utc", columns="machine_id", values=f"vibration_{suffix}_mms")
    st.line_chart(vibration, x_label="Time (UTC)", y_label="Vibration RMS (mm/s)", height=330)
    st.markdown("**Temperature (°C)**")
    temperature = frame.pivot(index="hour_utc", columns="machine_id", values=f"temperature_{suffix}_c")
    st.line_chart(temperature, x_label="Time (UTC)", y_label="Temperature (°C)", height=330)


def render_chat():
    if "active_chat_id" not in st.session_state:
        st.session_state.active_chat_id = None
    if "api_cost_total_usd" not in st.session_state:
        st.session_state.api_cost_total_usd = 0.0
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    cost_rates = api_cost_rates(model)
    connection = None
    try:
        connection = open_connection()
        ensure_chat_schema(connection)
        conversations = list_chats(connection)
        conversation_by_id = {row["chat_id"]: row for row in conversations}
        active_id = st.session_state.active_chat_id
        if active_id not in conversation_by_id:
            active_id = None

        with st.sidebar:
            st.header("Sources")
            st.caption("MySQL / SOPs / images / sensor logs / spares / audit reports")
            st.caption(f"MySQL target: {os.getenv('MYSQL_DATABASE', '(not set)')} at {os.getenv('MYSQL_HOST', '127.0.0.1')}:{os.getenv('MYSQL_PORT', '3307')}")
            st.caption("CMMS records are read-only. OCR values require human review.")
            st.caption("Assistant guidance: RAG_SKILL.md is loaded on each question.")
            st.caption("Chat history is stored in MySQL and shared by users of this local database.")
            with st.expander("What I can handle"):
                st.markdown(
                    "**Service history**\n"
                    "Search work orders by machine, type, and exact day, month, or year. "
                    "Requests for service records return a newest-first table with MySQL citations.\n\n"
                    "**Incidents and procedures**\n"
                    "Ask about incident history, OCR review status, nameplates, SOP text, and spare parts. "
                    "Incident severity keeps the pre-July 2025 and new WSH scales distinct.\n\n"
                    "**Sensor trends**\n"
                    "Use the Sensor Trends tab to chart hourly mean or maximum vibration and temperature "
                    "for selected machines and date ranges. Sustained shifts or repeated spikes may warrant "
                    "maintenance review, but are not an automatic diagnosis.\n\n"
                    "**Limits**\n"
                    "Chat RAG has whole-period sensor summaries, not hourly trend calculations. Sensor charts "
                    "are descriptive, not diagnoses; no alert thresholds are configured. "
                    "OCR values can be missing or wrong and need human verification. Employee details "
                    "and unprocessed image contents are not provided."
                )
            if st.button("New chat", icon=":material/add:"):
                connection.close()
                connection = None
                st.session_state.active_chat_id = None
                st.rerun()
            options = [None] + [row["chat_id"] for row in conversations]
            labels = {row["chat_id"]: row["title"] for row in conversations}
            current_index = options.index(active_id) if active_id in options else 0
            selected_id = st.selectbox(
                "Saved conversations", options, index=current_index,
                format_func=lambda chat_id: "New conversation" if chat_id is None else labels[chat_id],
                key=f"saved_conversation_{active_id or 'new'}",
            )
            active_id = selected_id
            st.session_state.active_chat_id = active_id
            if active_id:
                with st.popover("Delete selected chat"):
                    confirmed = st.checkbox("Delete this saved conversation and its messages")
                    if st.button("Delete permanently", disabled=not confirmed):
                        delete_chat(connection, active_id)
                        connection.close()
                        connection = None
                        st.session_state.active_chat_id = None
                        st.rerun()
            st.metric("Saved conversations", len(conversations))
            st.caption(f"Model: {model}")
            st.metric(
                "Estimated API cost (session)",
                f"${st.session_state.api_cost_total_usd:.6f}" if cost_rates else "Not configured",
            )
            if cost_rates:
                st.caption(
                    f"Rates: ${cost_rates[0]:g} input / ${cost_rates[1]:g} output per 1M tokens. "
                    "Session total resets when this Streamlit session ends."
                )
            else:
                st.caption("Set OPENAI_INPUT_COST_PER_1M_USD and OPENAI_OUTPUT_COST_PER_1M_USD for this endpoint/model.")

        messages = load_chat_messages(connection, active_id) if active_id else []
        connection.close()
        connection = None
    except Exception as error:
        st.error(f"MySQL chat history is unavailable: {error}")
        if connection is not None:
            connection.close()
        return

    token_total = sum(int(message.get("token_count", 0) or 0) for message in messages)
    st.session_state.tokens = token_total
    for message in messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            show_evidence(message.get("sources", []))
    question = st.chat_input("Ask about a machine or safety procedure")
    if not question:
        return
    history = [{"role": message["role"], "content": message["content"]}
               for message in messages[-6:]]
    sources, warnings, tokens = [], [], 0
    request_cost = None
    started = time.perf_counter()
    answer = input_refusal(question)
    ambiguous_date = partial_work_order_date(question)
    if answer is None and ambiguous_date:
        day, month, raw_date = ambiguous_date
        answer = (f"I read `{raw_date}` as {day} {calendar.month_name[month]}, but the year is missing. "
                  "Which year should I search? I haven't queried the work orders yet.")
    if answer is None:
        with st.spinner("Checking sources"):
            corpus, warnings = load_sources()
            retrieval_question = question
            previous = next((item["content"] for item in reversed(history)
                             if item["role"] == "user"), "")
            if re.fullmatch(r"20\d{2}", question.strip()):
                if partial_work_order_date(previous):
                    retrieval_question = resolve_partial_work_order_date(previous, int(question.strip()))
            elif not any(character.isdigit() for character in question):
                retrieval_question = previous + " " + question
            table_request = is_history_table_request(retrieval_question)
            combined_history = bool(re.search(r"\b(?:incident|near.miss)\b", retrieval_question, re.I)
                                    and re.search(r"\b(?:service|servicing|work.order|maintenance)\b", retrieval_question, re.I))
            sources = retrieve(retrieval_question, corpus, limit=50 if combined_history else 10 if table_request else 5)
            if not sources:
                if combined_history:
                    answer = "I couldn't find matching incident or service records for the requested period in MySQL."
                elif table_request and is_work_order_table_request(retrieval_question):
                    answer = "I couldn't find work orders matching the requested machine and date range in MySQL `work_orders`."
                elif table_request:
                    answer = "I couldn't find incident records matching the requested date range in the available sources."
                else:
                    answer = "I could not find evidence to answer that question. Specify an asset tag or SOP topic."
            elif combined_history:
                answer = format_combined_history_table(sources)
            elif table_request and is_work_order_table_request(retrieval_question):
                answer = format_work_order_table(sources)
            elif table_request:
                answer = format_incident_table(sources)
            elif not os.getenv("OPENAI_API_KEY"):
                answer = "The AI endpoint is not configured. Retrieved evidence is available below; no AI answer was generated."
            else:
                try:
                    client = OpenAI(
                        api_key=os.environ["OPENAI_API_KEY"],
                        base_url=os.getenv("OPENAI_BASE_URL") or None,
                        timeout=30, max_retries=1,
                    )
                    evidence = serialize_evidence(sources)
                    response = client.chat.completions.create(
                        model=model,
                        temperature=0, max_tokens=700,
                        messages=[{"role": "system", "content": load_system_prompt()}]
                        + history + [{"role": "user", "content":
                                      f"Question: {question}\nSource availability warnings: {warnings}\nRetrieved evidence:\n{evidence}"}],
                    )
                    answer = validate_answer(response.choices[0].message.content or "", sources)
                    tokens = response.usage.total_tokens if response.usage else 0
                    request_cost = estimate_api_cost(response.usage, model)
                    if request_cost is not None:
                        st.session_state.api_cost_total_usd += request_cost
                except OpenAIError:
                    answer = "The AI endpoint is unavailable. I could not generate an answer; review the retrieved evidence below."
    for warning in warnings:
        st.warning(warning)
    st.markdown(answer)
    show_evidence(sources)
    cost_text = f" / ~${request_cost:.6f}" if request_cost is not None else ""
    st.caption(f"{len(sources)} sources / {time.perf_counter() - started:.1f}s / {tokens} API tokens{cost_text}")

    try:
        connection = open_connection()
        ensure_chat_schema(connection)
        if active_id is None:
            active_id = create_chat(connection, question)
            st.session_state.active_chat_id = active_id
        append_chat_turn(connection, active_id, question, answer, sources, tokens)
        st.session_state.tokens = token_total + tokens
    except Exception as error:
        st.error(f"This response could not be saved to MySQL chat history: {error}")
    finally:
        if connection is not None:
            connection.close()
    st.rerun()


def main():
    load_dotenv(ROOT / ".env", override=True)
    st.set_page_config(page_title="Jurong Marine Maintenance", page_icon=":wrench:", layout="wide")
    st.title("Jurong Marine Maintenance")
    assistant_tab, review_tab, sensor_tab = st.tabs(["Assistant", "OCR Review", "Sensor Trends"])
    with assistant_tab:
        render_chat()
    with review_tab:
        render_review()
    with sensor_tab:
        render_sensor_trends()


if __name__ == "__main__":
    main()