"""Constants and paths shared by the jm_rag modules."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSET_PATTERN = re.compile(r"\b(?:CNC|CRN|LTH|MILL|PMP|WELD|BLAST|CMP)-[A-Z0-9]+\b", re.I)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
PROCESSED_AUDITS = {"sensor_data_audit.md", "nameplate_ocr_audit.md", "comparison.md"}

# Last day covered by the data package. Not used by any code path yet; Phase 3 and 4 use it.
DATA_END = date(2026, 6, 30)

MONTH_NUMBERS = {name.casefold(): number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
MONTH_NUMBERS.update({name[:3].casefold(): number for name, number in
                      ((name, number) for number, name in enumerate(
                          ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1))})
MONTH_NUMBERS["sept"] = 9
