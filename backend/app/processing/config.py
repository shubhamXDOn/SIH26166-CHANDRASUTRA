"""M2 processing configuration (registered, explicit, inspectable)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import m2_config


def _path(params: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    node: Any = params
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


@dataclass
class ProcessingConfig:
    """Snapshot of the M2 engineering configuration.

    ``parameters`` is exactly what the pipeline executed with and is written
    into every provenance manifest for reproducibility.
    """

    configuration_id: str
    configuration_version: int
    name: str
    source_reference: str
    parameters: dict[str, Any] = field(default_factory=dict)

    # -- typed parameter readers --------------------------------------------
    def p(self, *keys: str, default: Any = None) -> Any:
        return _path(self.parameters, list(keys), default)

    @property
    def crop_size_px(self) -> int:
        return int(self.p("crops", "size_px", default=512))

    @property
    def crop_stride_px(self) -> int:
        return int(self.p("crops", "stride_px", default=256))

    @property
    def min_tile_width_px(self) -> int:
        return int(self.p("crops", "min_tile_width_px", default=16))

    @property
    def min_tile_height_px(self) -> int:
        return int(self.p("crops", "min_tile_height_px", default=16))

    @property
    def min_valid_fraction(self) -> float:
        return float(self.p("crops", "min_valid_fraction", default=0.5))

    @property
    def min_overlap_px(self) -> int:
        return int(self.p("overlap", "min_overlap_px", default=64))

    @property
    def texture_low_dn(self) -> float:
        return float(self.p("condition", "texture_low_dn", default=8.0))

    @property
    def texture_high_dn(self) -> float:
        return float(self.p("condition", "texture_high_dn", default=60.0))

    @property
    def empty_valid_fraction(self) -> float:
        return float(self.p("condition", "empty_valid_fraction", default=0.02))

    @property
    def required_readiness(self) -> list[str]:
        return list(self.p("matcher_readiness", "required", default=[]))

    @property
    def radiometric_status(self) -> dict:
        mode = self.p("normalization", "radiometric", default="not_applicable")
        return {
            "mode": mode,
            "applied": mode == "applied",  # always false in M2 until real calibration metadata
            "status": "NOT_APPLICABLE" if mode == "not_applicable" else "UNKNOWN",
            "reason": self.p("normalization", "radiometric_reason", default=""),
        }

    def as_manifest_snapshot(self) -> dict:
        """Public, JSON-safe snapshot recorded in the provenance manifest."""
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "source_reference": self.source_reference,
            "parameters": self.parameters,
        }


def load_processing_config(configuration_id: str | None = None) -> ProcessingConfig:
    """Load the registered M2 configuration (only PC-M2-001 exists in M2).

    Unknown Configuration IDs are rejected loudly — no silent fallback to a
    different config than the one requested.
    """
    raw = m2_config()
    known_id = raw.get("configuration_id", "PC-M2-001")
    requested = (configuration_id or known_id).strip()
    if requested != known_id:
        raise ValueError(
            f"Unknown processing configuration '{requested}'. The only registered "
            f"M2 configuration is '{known_id}'.",
        )
    return ProcessingConfig(
        configuration_id=known_id,
        configuration_version=int(raw.get("configuration_version", 1)),
        name=str(raw.get("name", "Trustworthy Preprocessing and Lunar Scene Conditioning")),
        source_reference=str(raw.get("source_reference", "")),
        parameters=dict(raw.get("defaults") or {}),
    )


def configurations_public() -> list[dict]:
    """The runnable configurations exposed by /api/processing/configurations."""
    try:
        cfg = load_processing_config()
    except ValueError:
        return []
    return [
        {
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "name": cfg.name,
            "source_reference": cfg.source_reference,
            "display_only": {
                "normalization": cfg.p("normalization", "display", default="percentile_1_99"),
                "radiometric": cfg.radiometric_status["status"],
                "crop_size_px": cfg.crop_size_px,
                "resampling_applied": bool(cfg.p("resampling", "applied", default=False)),
                "required": cfg.required_readiness,
            },
        }
    ]