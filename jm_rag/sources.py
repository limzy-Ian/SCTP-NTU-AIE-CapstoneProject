"""Assemble the full source list from MySQL, documents, spares, processed OCR and images."""
from __future__ import annotations

from jm_rag import config
from jm_rag.common import _source
from jm_rag.config import ASSET_PATTERN, IMAGE_EXTENSIONS
from jm_rag.guardrails.sanitize import sanitize_sources, sanitize_text
from jm_rag.prompt import APP_CAPABILITY_TEXT
from jm_rag.sources_files import _load_text_documents, load_spares_sources
from jm_rag.sources_mysql import _load_mysql_sources
from jm_rag.sources_ocr import _load_processed_audits, load_processed_ocr_sources


def load_sources() -> tuple[list[dict], list[str]]:
    sources = [_source(
        "Assistant capability guide", APP_CAPABILITY_TEXT,
        "Application behavior: app.py and RAG_SKILL.md", source_type="app_capability",
    )]
    warnings = []
    image_names = _load_mysql_sources(sources, warnings)
    sources.extend(_load_text_documents(config.ROOT / "data" / "docs"))
    try:
        sources.extend(load_spares_sources())
    except (ImportError, OSError, ValueError) as error:
        warnings.append(f"Tabular spares unavailable: {type(error).__name__}.")
    processed_ocr_sources = load_processed_ocr_sources()
    sources.extend(processed_ocr_sources)
    image_names.update(source["image"] for source in processed_ocr_sources if source.get("image"))
    sources.extend(_load_processed_audits())

    images_root = config.ROOT / "data" / "images"
    if images_root.is_dir():
        all_images = [path for path in images_root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        unindexed_images = []
        for path in all_images:
            if path.name not in image_names:
                unindexed_images.append(path)
                match = ASSET_PATTERN.search(path.stem.replace("_", " ").upper())
                sources.append(_source(
                    f"{path.name} / image awaiting OCR review",
                    "Image source exists but has no matching OCR staging record. Do not infer values without image review.",
                    path.relative_to(config.ROOT).as_posix(),
                    asset_tag=match.group(0) if match else None, image=path.name,
                    image_folder=path.parent.relative_to(images_root).as_posix(), source_type="image_unindexed",
                ))
        if unindexed_images:
            warnings.append(f"{len(unindexed_images)} source images have no processed or MySQL OCR record; image-only evidence is not parsed.")

    if not sources:
        warnings.append("No retrievable sources were found.")
    # Every loader's output passes through one gate: names, IDs, keys and the reviewer field are removed.
    return sanitize_sources(sources), [sanitize_text(warning) for warning in warnings]
