"""Data directory architecture tests."""

from __future__ import annotations

import backend.app.config as cfg
from backend.app.data import DATA_TREE, RAW_IDS, data_directory_status, ensure_derived_directories


def test_data_tree_contains_expected_logical_locations():
    required = {
        "raw_ohrc",
        "raw_tmc2",
        "metadata",
        "derived_preprocessed",
        "derived_crops",
        "derived_matches",
        "derived_registrations",
        "derived_visualizations",
    }
    assert required.issubset(set(DATA_TREE))


def test_raw_ids_are_separate_from_derived():
    assert RAW_IDS == {"raw_ohrc", "raw_tmc2", "raw_iirs", "raw_lroc"}
    derived_ids = {k for k in DATA_TREE if k.startswith("derived_")}
    assert derived_ids.isdisjoint(RAW_IDS)


def test_directories_resolve_under_data_root(tmp_path):
    s = cfg.Settings(data_root=str(tmp_path), _env_file=None)
    ensure_derived_directories(s)
    info = {d.id: d for d in data_directory_status(s)}

    assert info["raw_ohrc"].path.startswith(str(tmp_path))
    assert info["raw_ohrc"].exists is False  # raw dirs are NOT auto-created
    assert info["derived_crops"].exists is True  # derived dirs are self-created
    assert info["metadata"].exists is True


def test_ensure_derived_never_creates_raw(tmp_path):
    s = cfg.Settings(data_root=str(tmp_path), _env_file=None)
    ensure_derived_directories(s)
    for raw_id in RAW_IDS:
        assert not (tmp_path / DATA_TREE[raw_id][0]).exists()