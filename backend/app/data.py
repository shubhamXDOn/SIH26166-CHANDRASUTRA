"""Data architecture service.

Defines the canonical raw/derived data tree and exposes a status endpoint so
the UI can display *real* on-disk readiness (not fabricated numbers).

Raw data is treated as immutable by policy (see data/README.md). Nothing in
this module writes to data/raw; it only resolves and inspects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Settings

# Logical structure. Keys are ids used by the API/UI; values are relative
# paths under the data root.
DATA_TREE: dict[str, tuple[str, str]] = {
    # (logical id): (relative path, description)
    "raw_ohrc": ("raw/ohrc", "Chandrayaan-2 OHRC imagery (raw, immutable)"),
    "raw_tmc2": ("raw/tmc2", "Chandrayaan-2 TMC-2 imagery (raw, immutable)"),
    "raw_iirs": ("raw/iirs", "Chandrayaan-2 IIRS data (raw, immutable)"),
    "raw_lroc": ("raw/lroc", "LROC reference layer for validation (raw)"),
    "metadata": ("metadata", "Acquisition metadata and PDS4 labels (structured)"),
    "derived_processing": ("derived/processing", "Per-pair preprocessing runs, crops/tiles, condition diagnostics and provenance manifests (M2)"),
    "derived_preprocessed": ("derived/preprocessed", "Validated, safely preprocessed products"),
    "derived_crops": ("derived/crops", "Overlap-confirmed crops/tiles used for matching"),
    "derived_matches": ("derived/matches", "Matcher outputs and candidate correspondences"),
    "derived_registrations": ("derived/registrations", "Registration models and overlays"),
    "derived_visualizations": ("derived/visualizations", "Report-ready figures and overlays"),
}

RAW_IDS = {"raw_ohrc", "raw_tmc2", "raw_iirs", "raw_lroc"}


@dataclass
class DirectoryInfo:
    id: str
    path: str
    description: str
    exists: bool
    is_raw: bool


def data_directory_status(settings: Settings) -> list[DirectoryInfo]:
    root = settings.data_root_path
    result: list[DirectoryInfo] = []
    for dir_id, (rel, description) in DATA_TREE.items():
        path = root / rel
        result.append(
            DirectoryInfo(
                id=dir_id,
                path=str(path),
                description=description,
                exists=path.is_dir(),
                is_raw=dir_id in RAW_IDS,
            )
        )
    return result


def ensure_derived_directories(settings: Settings) -> None:
    """Create derived/metadata directories at startup (never raw/)."""
    root = settings.data_root_path
    for dir_id, (rel, _desc) in DATA_TREE.items():
        if dir_id in RAW_IDS:
            continue
        (root / rel).mkdir(parents=True, exist_ok=True)