"""Deprecated shim. The code now lives in the ``jm_rag`` package.

This module re-exports every name the old single-file module had, so existing imports
(``app.py``, ``tests/``) keep working while they are migrated. New code should import
from ``jm_rag`` directly. The shim is removed once nothing imports it.
"""
# ruff: noqa: F401
from __future__ import annotations

import importlib as _importlib
import sys as _sys
import types as _types

from jm_rag.common import _source
from jm_rag.config import (
    ASSET_PATTERN, IMAGE_EXTENSIONS, MONTH_NUMBERS, PROCESSED_AUDITS, ROOT,
)
from jm_rag.dates import (
    parse_date_window, parse_explicit_date, partial_work_order_date,
    resolve_partial_work_order_date,
)
from jm_rag.guardrails.input_guard import input_refusal
from jm_rag.intents import (
    is_history_table_request, is_incident_query, is_work_order_table_request,
)
from jm_rag.prompt import (
    APP_CAPABILITY_TEXT, SYSTEM_PROMPT, load_system_prompt, serialize_evidence,
)
from jm_rag.retrieval import retrieve
from jm_rag.sensors import build_sensor_monthly_trend_sources
from jm_rag.sources import load_sources
from jm_rag.sources_files import _load_text_documents, load_spares_sources
from jm_rag.sources_mysql import _load_mysql_sources, _query_one, _query_rows
from jm_rag.sources_ocr import _load_processed_audits, load_processed_ocr_sources
from jm_rag.tables import (
    format_combined_history_table, format_incident_table, format_work_order_table,
)
from jm_rag.validator import validate_answer
from scripts.ocr_review import effective_record, ensure_review_table, open_connection

# Legacy patching support: tests patch ``scripts.maintenance_rag.ROOT`` and
# ``scripts.maintenance_rag.open_connection``. The code that reads those names now lives in
# jm_rag, so assignments on this module are forwarded to the jm_rag module that uses them.
_FORWARDED_NAMES = {
    "ROOT": ("jm_rag.config", "ROOT"),
    "open_connection": ("jm_rag.sources_mysql", "open_connection"),
}


class _ForwardingModule(_types.ModuleType):
    def __setattr__(self, name, value):
        target = _FORWARDED_NAMES.get(name)
        if target is not None:
            setattr(_importlib.import_module(target[0]), target[1], value)
        super().__setattr__(name, value)


_sys.modules[__name__].__class__ = _ForwardingModule
