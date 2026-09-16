from __future__ import annotations

import time

from backend.app.config import rfc3339_now


def build_trust_manifest(
    pair_id: str,
    trust_config_id: str,
    trust_config_version: str,
    proc_cfg: str,
    matcher_cfg: str,
    tiles_processed: int,
    trusted_tiles: int,
    rejected_tiles: int,
    total_runtime: float,
    reason_counts: dict[str, int],
) -> dict:
    return {
        "pair_id": pair_id,
        "trust_configuration_id": trust_config_id,
        "trust_configuration_version": trust_config_version,
        "processing_configuration_id": proc_cfg,
        "matcher_configuration_id": matcher_cfg,
        "generated_at": rfc3339_now(),
        "processing_summary": {
            "tiles_processed": tiles_processed,
            "trusted_tiles": trusted_tiles,
            "rejected_tiles": rejected_tiles,
            "total_runtime_seconds": round(total_runtime, 4),
        },
        "reason_distribution": reason_counts,
    }
