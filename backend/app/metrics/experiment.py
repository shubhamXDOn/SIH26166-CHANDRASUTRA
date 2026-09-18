"""M7 experiment identity — deterministic EXP-<hash> ids.

The experiment ID is derived solely from the pair, the configuration chain
(M2..M7 Configuration IDs + versions) and the hashes of the actual input
artefacts (selected evidence, scene mapping, fitted transform). It is
byte-deterministic across runs with unchanged inputs; timestamps are excluded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.app.config import rfc3339_now
from backend.app.registration.provenance import sha256_of


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def experiment_id_from_seed(seed: dict) -> str:
    digest = hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()
    return f"EXP-{digest[:12].upper()}"


def _hash_if_present(path: Path) -> str | None:
    if path.is_file():
        return sha256_of(path)
    return None


def build_experiment_seed(
    pair_id: str,
    configuration_chain: dict,
    m3_run: Path | None,
    m4_run: Path | None,
    m5_run: Path | None,
    m6_run: Path | None,
    data_root: Path,
) -> dict:
    """Deterministic seed: pair + configuration chain + input artefact hashes."""

    def _rel(p: Path | None) -> str | None:
        if p is None:
            return None
        try:
            return p.relative_to(data_root).as_posix()
        except ValueError:
            return p.as_posix()

    seed_chain = {k: v for k, v in configuration_chain.items() if k != "source"}

    return {
        "pair_id": pair_id,
        "configuration_chain": seed_chain,
        "input_hashes": {
            "m3_summary": _hash_if_present(m3_run / "summary.json") if m3_run else None,
            "m4_trusted_correspondences": _hash_if_present(m4_run / "trusted_correspondences.npz") if m4_run else None,
            "m5_selected_correspondences": _hash_if_present(m5_run / "selected_correspondences.npz") if m5_run else None,
            "m5_mapping": _hash_if_present(m5_run / "mapping.json") if m5_run else None,
            "m6_transform": _hash_if_present(m6_run / "transform.json") if m6_run else None,
            "m6_diagnostics": _hash_if_present(m6_run / "diagnostics.json") if m6_run else None,
            "m6_validation": _hash_if_present(m6_run / "validation.json") if m6_run else None,
        },
        "experiment_policy": {
            "reference_dataset": "NOT_AVAILABLE",
            "provenance": "M2->M7",
        },
        "input_artefact_rel": {
            "m3": _rel(m3_run / "summary.json") if m3_run else None,
            "m5": _rel(m5_run / "selected_correspondences.npz") if m5_run else None,
            "m6": _rel(m6_run / "transform.json") if m6_run else None,
        },
    }


def build_experiment_json(
    pair_id: str,
    configuration_chain: dict,
    m3_run: Path | None,
    m4_run: Path | None,
    m5_run: Path | None,
    m6_run: Path | None,
    data_root: Path,
    generated_at: str | None = None,
) -> dict:
    seed = build_experiment_seed(
        pair_id, configuration_chain, m3_run, m4_run, m5_run, m6_run, data_root)
    return {
        "experiment_id": experiment_id_from_seed(seed),
        "seed": seed,
        "generated_at_utc": generated_at or rfc3339_now(),
        "note": (
            "Deterministic identity over inputs; timestamps are metadata only and "
            "do not change the experiment ID. Reference dataset is NOT_AVAILABLE."
        ),
    }