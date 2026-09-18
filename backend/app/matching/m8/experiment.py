"""M8 experiment identity — deterministic EXP-<hash> (extended M7 pattern).

The M8 experiment seed covers the pair, the configuration chain, the M8
matcher/model identity and the hashes of the actual input artefacts (M2 tiles,
M3 decisions, per-matcher candidate artifacts). Deterministic across reruns;
timestamps excluded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ...config import rfc3339_now
from ...registration.provenance import sha256_of


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def experiment_id_from_seed(seed: dict) -> str:
    digest = hashlib.sha256(_canonical_json(seed).encode("utf-8")).hexdigest()
    return f"EXP-{digest[:12].upper()}"


def _hash_if_present(path: Path | None) -> str | None:
    if path is not None and Path(path).is_file():
        return sha256_of(path)
    return None


def build_m8_experiment_seed(
    pair_id: str,
    configuration_chain: dict,
    matcher_model_identity: dict,
    m8_run: Path,
    data_root: Path,
) -> dict:
    try:
        rel = m8_run.relative_to(data_root).as_posix()
    except ValueError:
        rel = m8_run.as_posix()
    return {
        "pair_id": pair_id,
        "configuration_chain": configuration_chain,
        "matcher_model_identity": matcher_model_identity,
        "input_hashes": {
            "m8_status": _hash_if_present(m8_run / "m8_status.json"),
            "m8_summary": _hash_if_present(m8_run / "summary.json"),
            "m8_routing": _hash_if_present(m8_run / "routing" / "routing.json"),
            "m8_candidates_index": _hash_if_present(m8_run / "candidates" / "candidates.json"),
        },
        "experiment_policy": {
            "reference_dataset": "NOT_AVAILABLE",
            "provenance": "M2->M3->M8",
        },
        "run_rel": rel,
    }


def build_m8_experiment_json(
    pair_id: str,
    configuration_chain: dict,
    matcher_model_identity: dict,
    m8_run: Path,
    data_root: Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    seed = build_m8_experiment_seed(pair_id, configuration_chain, matcher_model_identity, m8_run, data_root)
    return {
        "experiment_id": experiment_id_from_seed(seed),
        "seed": seed,
        "generated_at_utc": generated_at or rfc3339_now(),
        "note": (
            "M8 experiment identity is deterministic over the M8 configuration, "
            "matcher/model identity and input artificial hashes. "
            "Reference dataset is NOT_AVAILABLE."
        ),
    }