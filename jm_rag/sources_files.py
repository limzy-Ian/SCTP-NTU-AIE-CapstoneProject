"""Loaders for text documents (SOPs) and the spares workbook."""
from __future__ import annotations

import json
from pathlib import Path

from jm_rag import config
from jm_rag.common import _source


def _load_text_documents(folder: Path) -> list[dict]:
    sources = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            continue
        for offset in range(0, len(lines), 32):
            start = max(0, offset - 3)
            end = min(offset + 32, len(lines))
            chunk = "\n".join(lines[start:end]).strip()
            if chunk:
                path_label = path.relative_to(config.ROOT).as_posix() if path.is_relative_to(config.ROOT) else path.name
                location = f"{path_label} lines {start + 1}-{end}"
                sources.append(_source(path.name, chunk, location, source_type="document"))
    return sources


def load_spares_sources(folder: Path | None = None) -> list[dict]:
    from openpyxl import load_workbook

    folder = folder or config.ROOT / "data" / "tabular"
    sources = []
    for path in sorted(folder.glob("*.xlsx")):
        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook.worksheets:
                rows = sheet.iter_rows(values_only=True)
                headers = None
                header_row = 0
                for row_number, row in enumerate(rows, 1):
                    normalized = [str(value).strip() if value is not None else "" for value in row]
                    if any(value.casefold() in {"part no", "part number", "sku"} for value in normalized):
                        headers, header_row = normalized, row_number
                        break
                if headers is None:
                    continue
                for row_number, row in enumerate(rows, header_row + 1):
                    values = {headers[index]: value for index, value in enumerate(row)
                              if index < len(headers) and headers[index] and value is not None}
                    if not values:
                        continue
                    part = next((str(value) for key, value in values.items()
                                 if key.casefold() in {"part no", "part number", "sku"}), "")
                    machine = next((str(value) for key, value in values.items()
                                    if key.casefold() in {"for machine", "machine", "asset tag"}), None)
                    content = json.dumps(values, default=str, ensure_ascii=True)
                    searchable = (f"Critical spare part inventory. Part number: {part}. "
                                  f"Description: {values.get('Description', '')}. "
                                  f"Machine: {machine or ''}. Quantity in stock: {values.get('Qty', '')}. "
                                  f"Minimum quantity: {values.get('Min Qty', '')}. "
                                  f"Unit cost: {values.get('Unit Cost', '')}. "
                                  f"Lead time: {values.get('Lead Time', '')}. "
                                  f"Store location: {values.get('Location', '')}. Source row: {content}")
                    location = (f"{path.relative_to(config.ROOT).as_posix()} / {sheet.title} row {row_number}"
                                if path.is_relative_to(config.ROOT) else f"{path.name} / {sheet.title} row {row_number}")
                    sources.append(_source(
                        f"{path.name} / {part or sheet.title}",
                        "Workbook row; verify current stock with the storeman. " + searchable,
                        location,
                        asset_tag=machine, source_type="tabular",
                    ))
        finally:
            workbook.close()
    return sources
