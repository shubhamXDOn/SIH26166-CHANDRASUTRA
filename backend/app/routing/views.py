"""M6 adaptive matcher router — canonical condition/capability views.

The router only ever reasons over these declarative views:

    * ``condition_view`` — flat, JSON-safe facts gathered from the M2
      processing status and the M5 condition profile (never from a matcher
      run, never inferred GSD);
    * ``capability_view`` — live-probed matcher availability and device info
      (classical matchers are always present; deep matchers probe runtimes
      + checkpoints).

``KNOWN_VIEW_FIELDS`` is both the documentation of the view and the rule
validation whitelist (unknown fields fail configuration validation).
"""

from __future__ import annotations

from typing import Any

from ..config import m6_routing_config

# ---------------------------------------------------------------------------
# canonical view registry (used by rule validation)
# ---------------------------------------------------------------------------

KNOWN_VIEW_FIELDS: frozenset[str] = frozenset({
    # ---- gates (always strict booleans / stable strings) ------------------
    "input_valid",
    "processing_ready",
    "condition_profile_available",
    "condition_run_id",
    "synthetically_derived",
    "data_source_gate",
    "source_class_a",
    "source_class_b",
    "sensor_a",
    "sensor_b",
    "overlap_available",
    # ---- per-side intrinsic facts -----------------------------------------
    "a.textural_complexity",
    "a.textural_complexity_score",
    "a.dynamic_range",
    "a.invalid_fraction",
    "a.invalid_fraction_value",
    "a.laplacian_variance",
    "a.canny_edge_fraction",
    "a.entropy_bits",
    "b.textural_complexity",
    "b.textural_complexity_score",
    "b.dynamic_range",
    "b.invalid_fraction",
    "b.invalid_fraction_value",
    "b.laplacian_variance",
    "b.canny_edge_fraction",
    "b.entropy_bits",
    # ---- pair-level relationship facts ------------------------------------
    "pair.appearance_difference",
    "pair.appearance_difference_low",
    "pair.appearance_difference_high",
    "pair.gsd_ratio",
    "pair.gsd_ratio_known",
    "pair.gsd_ratio_medium",
    "pair.gsd_ratio_large",
    "pair.absolute_pixel_ratio",
    "pair.texture_complexity_high",
    "pair.texture_complexity_low",
    "pair.max_textural_complexity",
    "pair.worst_invalid_fraction",
    # ---- capability facts --------------------------------------------------
    "capability.sift",
    "capability.orb",
    "capability.akaze",
    "capability.superpoint_superglue",
    "capability.loftr",
    "device.cuda_available",
})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bin_str(value: Any) -> str:
    if not isinstance(value, dict):
        return "UNKNOWN"
    val = value.get("bin")
    return str(val) if isinstance(val, str) else "UNKNOWN"


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _bool(value: Any) -> bool:
    return bool(value)


# ---------------------------------------------------------------------------
# condition view from M5 profile + processing status + pair record
# ---------------------------------------------------------------------------

def extract_condition_view(
    condition_payload: dict[str, Any] | None,
    processing_status: dict[str, Any] | None,
    record: Any | None,
    *,
    appearance_policy: dict[str, float] | None = None,
    scale_policy: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build the flat, JSON-safe condition view the engine evaluates.

    ``condition_payload`` is the FULL M5 condition artifact (not the summary).
    When it is missing or not SUCCESS the per-side facts stay None but the
    gate facts are still strict so pre-rules block correctly.
    """
    if appearance_policy is None:
        raw = m6_routing_config()
        defaults = raw.get("defaults") or {}
        app = (defaults.get("policy") or {}).get("appearance") or {}
        appearance_policy = {
            "difference_low_lt": float(app.get("difference_low_lt", 0.25)),
            "difference_high_ge": float(app.get("difference_high_ge", 0.55)),
        }
    if scale_policy is None:
        raw = m6_routing_config()
        defaults = raw.get("defaults") or {}
        sc = (defaults.get("policy") or {}).get("scale") or {}
        scale_policy = {
            "gsd_ratio_medium_ge": float(sc.get("gsd_ratio_medium_ge", 1.35)),
            "gsd_ratio_large_ge": float(sc.get("gsd_ratio_large_ge", 2.0)),
        }

    processing_state = (processing_status or {}).get("state") or ""
    products = (processing_status or {}).get("products") or {}
    processing_ready = processing_state == "READY_FOR_MATCHING" and bool(products)
    overlap_available = bool(products)

    profile_ok = bool(
        condition_payload is not None
        and condition_payload.get("status") == "SUCCESS"
        and condition_payload.get("intrinsic_image_condition")
        and condition_payload.get("pair_comparison")
    )
    input_valid = processing_ready and profile_ok
    condition_run_id = (condition_payload or {}).get("run_id") if condition_payload else None
    if condition_payload is not None and condition_payload.get("status") != "SUCCESS":
        condition_run_id = (condition_payload or {}).get("run_id")

    view: dict[str, Any] = {
        "input_valid": input_valid,
        "processing_ready": processing_ready,
        "condition_profile_available": profile_ok,
        "condition_run_id": condition_run_id,
        "synthetically_derived": bool(condition_payload and condition_payload.get("synthetically_derived")),
        "data_source_gate": str((condition_payload or {}).get("source_gate") or (record.source_class_a if record else "")),
        "source_class_a": str(getattr(record, "source_class_a", "") or ""),
        "source_class_b": str(getattr(record, "source_class_b", "") or ""),
        "sensor_a": str(getattr(record, "sensor_a", "") or ""),
        "sensor_b": str(getattr(record, "sensor_b", "") or ""),
        "overlap_available": overlap_available,
    }

    intrinsic = (condition_payload or {}).get("intrinsic_image_condition") or {}
    comparison = (condition_payload or {}).get("pair_comparison") or {}

    side_facts: dict[str, Any] = {}
    for side_key, prefix in (("side_a", "a"), ("side_b", "b")):
        side = intrinsic.get(side_key) or {}
        cls = side.get("classification") or {}
        texture = cls.get("textural_complexity") or {}
        dynamic = cls.get("dynamic_range") or {}
        invalid = cls.get("invalid_fraction") or {}
        texture_val = _bin_str(texture)
        side_facts[f"{prefix}.textural_complexity"] = texture_val
        side_facts[f"{prefix}.textural_complexity_score"] = _num(texture.get("value"))
        side_facts[f"{prefix}.dynamic_range"] = _bin_str(dynamic)
        side_facts[f"{prefix}.invalid_fraction"] = _bin_str(invalid)
        side_facts[f"{prefix}.invalid_fraction_value"] = _num(invalid.get("value"))
        side_facts[f"{prefix}.laplacian_variance"] = _num((side.get("texture") or {}).get("laplacian_variance"))
        side_facts[f"{prefix}.canny_edge_fraction"] = _num((side.get("texture") or {}).get("canny_edge_fraction"))
        side_facts[f"{prefix}.entropy_bits"] = _num((side.get("appearance") or {}).get("entropy_bits"))

    appearance = comparison.get("appearance") or {}
    hist_distance = _num(appearance.get("histogram_distance_chi_square"))
    scale = comparison.get("scale") or {}
    gsd_ratio = _num(scale.get("gsd_ratio_relationship"))
    native_scale = (scale.get("native_scale_gap") or {})
    abs_pixel_ratio = _num(native_scale.get("absolute_pixel_ratio")) or 1.0
    coverage = comparison.get("coverage") or {}

    low_lt = appearance_policy["difference_low_lt"]
    high_ge = appearance_policy["difference_high_ge"]
    medium_ge = scale_policy["gsd_ratio_medium_ge"]
    large_ge = scale_policy["gsd_ratio_large_ge"]

    tex_high = any(
        side_facts.get(f"{p}.textural_complexity") == "HIGH"
        for p in ("a", "b")
    )
    tex_low = all(
        side_facts.get(f"{p}.textural_complexity") == "LOW"
        for p in ("a", "b")
    )

    view.update({
        "a.textural_complexity": side_facts.get("a.textural_complexity", "UNKNOWN"),
        "a.textural_complexity_score": side_facts.get("a.textural_complexity_score"),
        "a.dynamic_range": side_facts.get("a.dynamic_range", "UNKNOWN"),
        "a.invalid_fraction": side_facts.get("a.invalid_fraction", "UNKNOWN"),
        "a.invalid_fraction_value": side_facts.get("a.invalid_fraction_value"),
        "a.laplacian_variance": side_facts.get("a.laplacian_variance"),
        "a.canny_edge_fraction": side_facts.get("a.canny_edge_fraction"),
        "a.entropy_bits": side_facts.get("a.entropy_bits"),
        "b.textural_complexity": side_facts.get("b.textural_complexity", "UNKNOWN"),
        "b.textural_complexity_score": side_facts.get("b.textural_complexity_score"),
        "b.dynamic_range": side_facts.get("b.dynamic_range", "UNKNOWN"),
        "b.invalid_fraction": side_facts.get("b.invalid_fraction", "UNKNOWN"),
        "b.invalid_fraction_value": side_facts.get("b.invalid_fraction_value"),
        "b.laplacian_variance": side_facts.get("b.laplacian_variance"),
        "b.canny_edge_fraction": side_facts.get("b.canny_edge_fraction"),
        "b.entropy_bits": side_facts.get("b.entropy_bits"),
        "pair.appearance_difference": hist_distance,
        "pair.appearance_difference_low": _bool(hist_distance is not None and hist_distance < low_lt),
        "pair.appearance_difference_high": _bool(hist_distance is not None and hist_distance >= high_ge),
        "pair.gsd_ratio": gsd_ratio,
        "pair.gsd_ratio_known": gsd_ratio is not None,
        "pair.gsd_ratio_medium": _bool(gsd_ratio is not None and gsd_ratio >= medium_ge),
        "pair.gsd_ratio_large": _bool(gsd_ratio is not None and gsd_ratio >= large_ge),
        "pair.absolute_pixel_ratio": abs_pixel_ratio,
        "pair.texture_complexity_high": tex_high,
        "pair.texture_complexity_low": tex_low,
        "pair.max_textural_complexity": (
            "HIGH" if tex_high else ("LOW" if tex_low else "MEDIUM")
        ),
        "pair.worst_invalid_fraction": max(
            (
                _num(coverage.get("side_a_valid_fraction")) or 0.0,
                _num(coverage.get("side_b_valid_fraction")) or 0.0,
            )
        ),
    })
    return view


# ---------------------------------------------------------------------------
# capability view (live-probed)
# ---------------------------------------------------------------------------

def extract_capability_view(
    classical_capabilities: dict[str, Any] | None,
    deep_capabilities: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the flat capability view the engine consumes.

    ``classical_capabilities`` = ``BaselineMatcherService.capabilities_public()``
    ``deep_capabilities``     = ``DeepMatcherService.capabilities_public()``
    """
    classical = {}
    for probe in (classical_capabilities or {}).get("matchers") or []:
        matcher_id = str(probe.get("matcher_id") or probe.get("matcher") or "").strip()
        if matcher_id:
            classical[matcher_id] = _bool(probe.get("available", False))

    deep = {}
    for probe in (deep_capabilities or {}).get("matchers") or []:
        matcher_id = str(probe.get("matcher_id") or probe.get("matcher") or "").strip()
        if matcher_id:
            deep[matcher_id] = _bool(probe.get("available", False))

    device = (deep_capabilities or {}).get("device") or {}
    cuda = ((device.get("cuda_available") if isinstance(device, dict) else None)
            or (classical_capabilities or {}).get("cuda_available")
            or False)

    return {
        "capability.sift": _bool(classical.get("sift", False)),
        "capability.orb": _bool(classical.get("orb", False)),
        "capability.akaze": _bool(classical.get("akaze", False)),
        "capability.superpoint_superglue": _bool(deep.get("superpoint_superglue", False)),
        "capability.loftr": _bool(deep.get("loftr", False)),
        "device.cuda_available": _bool(cuda),
        "_classical": classical,
        "_deep": deep,
    }


def capability_summary(capability_view: dict[str, Any]) -> dict[str, Any]:
    """Lightweight public helper for the capability endpoint."""
    return {
        "classical": {k: capability_view.get(f"capability.{k}") for k in ("sift", "orb", "akaze")},
        "deep": {k: capability_view.get(f"capability.{k}") for k in ("superpoint_superglue", "loftr")},
        "device": {"cuda_available": capability_view.get("device.cuda_available")},
    }


__all__ = [
    "KNOWN_VIEW_FIELDS",
    "extract_condition_view",
    "extract_capability_view",
    "capability_summary",
]