"""M12 configuration freeze.

A configuration freeze records, for every stage M1..M10, the committed
configuration id + version plus a canonical SHA-256 of the effective
configuration document (sorted keys, no absolute ``source`` path). The M11
operational parameters are hashed from the effective :class:`Settings`
surface because M11 owns operations (nginx/compose/timeouts/demo mode), not a
YAML configuration section.

Reproducibility requires the configuration an experiment recorded to match the
committed chain; ``verify_configuration_freeze`` re-runs the chain against the
current committed configurations and reports ``VERIFIED``/``DRIFTED`` per stage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from backend.app.config import (
    m1_config,
    m2_config,
    m3_config,
    m4_config,
    m5_config,
    m6_config,
    m7_config,
    m8_config,
    m9_config,
    m10_config,
)

# (milestone, stage, getter, id field, version field)
_STAGES: list[tuple[str, str, Callable[[], dict[str, Any]], str | None, str | None]] = [
    ("M1", "core", m1_config, None, None),
    ("M2", "processing", m2_config, "configuration_id", "configuration_version"),
    ("M3", "matching", m3_config, "configuration_id", "configuration_version"),
    ("M4", "trust", m4_config, "trust_configuration_id", "trust_configuration_version"),
    ("M5", "spatial", m5_config, "spatial_reliability_configuration_id", "spatial_reliability_configuration_version"),
    ("M6", "registration", m6_config, "registration_configuration_id", "registration_configuration_version"),
    ("M7", "metrics", m7_config, "metrics_configuration_id", "metrics_configuration_version"),
    ("M8", "deep_matching", m8_config, "configuration_id", "configuration_version"),
    ("M9", "ai_explanations", m9_config, "ai_configuration_id", "ai_configuration_version"),
    ("M10", "authentication", m10_config, "authentication_configuration_id", "authentication_configuration_version"),
]

M12_OPERATIONS_STAGE = "M11"
M12_APPLICATION_PREFIX = "CHANDRASUTRA-SIH26166"


def canonical_config_json(config: dict[str, Any]) -> str:
    """Deterministic JSON of a config document (never includes ``source``)."""
    sans = {k: v for k, v in config.items() if k != "source"}
    return json.dumps(sans, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def operations_digest(settings: Any) -> str:
    """Deterministic digest of the M11 operational surface that affects runs."""
    payload = {
        "run_stale_budget_seconds": getattr(settings, "run_stale_budget_seconds", None),
        "demo_mode": getattr(settings, "demo_mode", None),
        "http_max_body_bytes": getattr(settings, "http_max_body_bytes", None),
        "auth_configured": bool(getattr(settings, "auth_configured", False)),
        "auth_token_expire_minutes": getattr(settings, "auth_token_expire_minutes", None),
        "history_size": getattr(settings, "history_size", None),
    }
    return sha256_hex(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str))


def configuration_chain(config_file: Path | None = None, settings: Any | None = None) -> dict[str, Any]:
    """Assemble the committed configuration chain with per-stage fingerprints.

    The overall fingerprint is a pure function of the stage digests, so equal
    chains yield equal fingerprints across machines and processes.
    """
    chain: list[dict[str, Any]] = []
    for milestone, stage, getter, id_key, ver_key in _STAGES:
        cfg = getter(config_file)
        chain.append({
            "milestone": milestone,
            "stage": stage,
            "configuration_id": cfg.get(id_key) if id_key else None,
            "configuration_version": cfg.get(ver_key) if ver_key else None,
            "sha256": sha256_hex(canonical_config_json(cfg)),
        })
    chain.append({
        "milestone": M12_OPERATIONS_STAGE,
        "stage": "operations",
        "configuration_id": getattr(settings, "app_version", "UNKNOWN") if settings is not None else None,
        "configuration_version": None,
        "sha256": operations_digest(settings) if settings is not None else None,
    })
    overall = sha256_hex(
        M12_APPLICATION_PREFIX + "|" + "|".join(stage["sha256"] for stage in chain)
    )
    return {
        "schema_version": "M12-CONFIG-FREEZE-001",
        "fingerprint": overall,
        "chain": chain,
        "note": "Canonical sorted-key digests; source paths excluded; equal chains -> equal fingerprints.",
    }


def verify_configuration_freeze(
    recorded: dict[str, Any],
    config_file: Path | None = None,
    settings: Any | None = None,
) -> dict[str, Any]:
    """Re-run the chain and report per-stage VERIFIED/DRIFTED/MISSING."""
    current = configuration_chain(config_file, settings=settings)
    current_by = {s["milestone"]: s for s in current["chain"]}
    stages: list[dict[str, Any]] = []
    for rec in (recorded or {}).get("chain", []):
        now = current_by.get(rec.get("milestone"))
        if now is None:
            stages.append({**rec, "status": "MISSING"})
            continue
        status = (
            "VERIFIED"
            if now.get("configuration_id") == rec.get("configuration_id")
            and now.get("sha256") == rec.get("sha256")
            else "DRIFTED"
        )
        stages.append({"milestone": rec.get("milestone"), "stage": rec.get("stage"), "status": status})
    status = "VERIFIED" if stages and all(s["status"] == "VERIFIED" for s in stages) else "DRIFTED"
    return {
        "status": status,
        "stages": stages,
        "recorded_fingerprint": (recorded or {}).get("fingerprint"),
        "recomputed_fingerprint": current.get("fingerprint"),
        "schema_version": current.get("schema_version"),
    }


def write_configuration_freeze(
    freeze: dict[str, Any],
    settings: Any,
    experiment_id: str,
    dest_dir: Path,
) -> Path:
    """Persist ``configurations.json`` into a final-evidence directory."""
    payload = {
        "experiment_id": experiment_id,
        "freeze": freeze,
    }
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / "configurations.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


__all__ = [
    "canonical_config_json",
    "sha256_hex",
    "operations_digest",
    "configuration_chain",
    "verify_configuration_freeze",
    "write_configuration_freeze",
]