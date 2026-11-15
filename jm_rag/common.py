"""Helpers shared by the source loaders."""
from __future__ import annotations


def _source(title: str, text: str, location: str, **metadata) -> dict:
    return {"title": title, "text": text, "location": location, **metadata}
