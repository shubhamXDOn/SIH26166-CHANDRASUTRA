"""Adaptive, explainable strategy engine for M3 matching.

A decision is a *routing* decision: given measured scene conditions, scale-gap
observations, adapter availability and the registered engineering scoring
weights (MC-M3-001), it picks the strategy most likely to yield candidate
correspondences — and records exactly why, including what it saw, what scored
what, which constraints fired, and which alternatives were considered.

Score discipline:
    * score = base + sum of measured boosts, clamped to [0, 1];
    * boost terms are additive, deterministic and taken from config;
    * a strategy unavailable in this build is recorded as UNAVAILABLE (never
      replaced by fabricated output);
    * the decision can NOT be echoed as a confidence or quality verdict.
"""

from __future__ import annotations

import datetime
from typing import Any

import numpy as np

from .adapters import STRATEGY_ORDER, all_matchers
from .config import MatcherConfig

TEXTURE_ORDINAL = {"BLOCKED": -1, "UNKNOWN": -1, "LOW": 0, "NORMAL": 1, "HIGH": 2}
SCALE_GAP_CLASSES = ("SMALL", "MEDIUM", "LARGE")


class StrategyDecision:
    """One explainable routing decision for one match tile."""

    def __init__(self, *, decision_id: str, tile_pair_a: str, tile_pair_b: str,
                 match_tile_id: str, configuration_id: str, pair_id: str,
                 inputs: dict[str, Any], scoring: dict[str, Any],
                 selected: str, rank_order: list[str], evidence: dict[str, Any]):
        self.decision_id = decision_id
        self.tile_pair_a = tile_pair_a
        self.tile_pair_b = tile_pair_b
        self.match_tile_id = match_tile_id
        self.configuration_id = configuration_id
        self.pair_id = pair_id
        self.inputs = inputs
        self.scoring = scoring
        self.selected = selected
        self.rank_order = rank_order
        self.evidence = evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "configuration_id": self.configuration_id,
            "pair_id": self.pair_id,
            "match_tile_id": self.match_tile_id,
            "tile_a": self.tile_pair_a,
            "tile_b": self.tile_pair_b,
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "inputs": self.inputs,
            "scoring": self.scoring,
            "selected_strategy": self.selected,
            "rank_by_score": self.rank_order,
            "evidence": self.evidence,
            "note": "Routing decision only — it is NOT a matcher/trust confidence or a quality verdict.",
        }


def _texture_signature(t_a: str, t_b: str) -> str:
    val = min(TEXTURE_ORDINAL.get(t_a, -1), TEXTURE_ORDINAL.get(t_b, -1))
    if val == -1:
        return "UNKNOWN"
    return {0: "LOW", 1: "NORMAL", 2: "HIGH"}[val]


def _contrast_signature(c_a: str, c_b: str) -> str:
    return "HIGH" if c_a == "HIGH" and c_b == "HIGH" else ("NORMAL" if c_a == "NORMAL" and c_b == "NORMAL" else "LOW")


def classify_scale_gap(gsd_a: float | None, gsd_b: float | None) -> dict[str, Any]:
    """Scale gap class from documented GSDs (SMALL <3x, MEDIUM <10x, LARGE >=10x)."""
    if not gsd_a or gsd_a <= 0 or not gsd_b or gsd_b <= 0:
        return {"class": "UNKNOWN", "ratio": None}
    ratio = max(gsd_a, gsd_b) / min(gsd_a, gsd_b)
    if ratio < 3.0:
        klass = "SMALL"
    elif ratio < 10.0:
        klass = "MEDIUM"
    else:
        klass = "LARGE"
    return {"class": klass, "ratio": round(float(ratio), 4)}


class AdaptiveStrategyEngine:
    def __init__(self, cfg: MatcherConfig):
        self.cfg = cfg
        self.scoring = cfg.scoring_params()
        self.constraints = cfg.constraint_params()

    def decide(
        self,
        *,
        pair_id: str,
        match_tile_id: str,
        tile_a: str,
        tile_b: str,
        sensor_a: str,
        sensor_b: str,
        condition_view: dict[str, Any],
        scale_gap: dict[str, Any],
        adjudicator: str = "adaptive_routing.mc_m3_001",
    ) -> dict[str, Any]:
        """Deterministic, explainable strategy selection for one match tile."""
        matchers = all_matchers()
        avail = {m.strategy_id: m.is_available() for m in matchers}
        family_of = {m.strategy_id: m.family for m in matchers}
        vf_a = float(condition_view.get("valid_fraction_a", 0.0) or 0.0)
        vf_b = float(condition_view.get("valid_fraction_b", 0.0) or 0.0)
        vf = round(min(vf_a, vf_b), 6)
        texture = _texture_signature(
            str(condition_view.get("texture_a", "UNKNOWN")),
            str(condition_view.get("texture_b", "UNKNOWN")),
        )
        contrast = _contrast_signature(
            str(condition_view.get("contrast_a", "NORMAL")),
            str(condition_view.get("contrast_b", "NORMAL")),
        )
        dyn_range = round(float(max(
            condition_view.get("dynamic_range_a", 0.0) or 0.0,
            condition_view.get("dynamic_range_b", 0.0) or 0.0,
        )), 6)
        gap_class = scale_gap.get("class", "UNKNOWN")

        rows: list[dict[str, Any]] = []
        for strategy in STRATEGY_ORDER:
            family = family_of.get(strategy, strategy)
            bp = self.scoring.get(family, {})
            cons = self.constraints.get(family, {})
            base = float(bp.get("base", 0.0))
            contributions: dict[str, float] = {"base": base}

            if not avail.get(strategy, False):
                rows.append({
                    "strategy": strategy,
                    "family": family,
                    "status": "UNAVAILABLE",
                    "score": 0.0,
                    "score_details": {"contributions": {"base": base}, "note": "adapter is not available in this build"},
                    "constraints": cons,
                })
                continue

            score = base
            contributions["texture"] = 0.0
            if texture in ("LOW", "NORMAL", "HIGH"):
                contribution = float(bp.get(f"texture_{texture.lower()}", 0.0))
                contributions["texture"] = contribution
                score += contribution
            if vf >= 0:
                contribution = float(bp.get("valid_fraction", 0.0)) * vf
                contributions["valid_fraction"] = contribution
                score += contribution
            if contrast == "HIGH" and "contrast_high" in bp:
                contributions["contrast_high"] = float(bp["contrast_high"])
                score += contributions["contrast_high"]
            gap_key = f"scale_gap_{gap_class.lower()}"
            if gap_class in SCALE_GAP_CLASSES and gap_key in bp:
                contributions["scale_gap"] = float(bp[gap_key])
                score += contributions["scale_gap"]

            score = float(np.clip(score, 0.0, 1.0))
            rejected_reason: str | None = None
            if "min_valid_fraction" in cons and vf < float(cons["min_valid_fraction"]):
                rejected_reason = (f"valid_fraction {vf} < min_valid_fraction {cons['min_valid_fraction']}")
            rows.append({
                "strategy": strategy,
                "family": family,
                "status": "SCORED" if rejected_reason is None else "CONSTRAINT_REJECTED",
                "score": round(score, 4),
                "score_details": {"contributions": {k: round(float(v), 4) for k, v in contributions.items()}},
                "constraints": cons,
                "rejected_reason": rejected_reason,
            })

        ranked = sorted(
            [r for r in rows if r["status"] == "SCORED"],
            key=lambda r: (-r["score"], STRATEGY_ORDER.index(r["strategy"])),
        )
        rank_order = [r["strategy"] for r in ranked]

        if ranked:
            selected = ranked[0]["strategy"]
        else:
            scored = [r for r in rows if r["status"] == "SCORED"]
            selected = scored[0]["strategy"] if scored else rows[0]["strategy"]

        inputs = {
            "pair_id": pair_id,
            "match_tile_id": match_tile_id,
            "tile_a": tile_a, "tile_b": tile_b,
            "sensor_a": sensor_a, "sensor_b": sensor_b,
            "condition_view": {
                "valid_fraction_a": vf_a, "valid_fraction_b": vf_b,
                "valid_fraction_effective": vf,
                "texture_a": condition_view.get("texture_a"), "texture_b": condition_view.get("texture_b"),
                "texture_signature": texture,
                "contrast_a": condition_view.get("contrast_a"), "contrast_b": condition_view.get("contrast_b"),
                "contrast_signature": contrast,
                "dynamic_range": dyn_range,
            },
            "scale_gap": scale_gap,
            "availability": avail,
            "adjudicator": adjudicator,
        }

        decision_id = f"{self.cfg.configuration_id}:{pair_id}:{match_tile_id}:v1"
        return StrategyDecision(
            decision_id=decision_id,
            tile_pair_a=tile_a,
            tile_pair_b=tile_b,
            match_tile_id=match_tile_id,
            configuration_id=self.cfg.configuration_id,
            pair_id=pair_id,
            inputs=inputs,
            scoring={r["strategy"]: r for r in rows},
            selected=selected,
            rank_order=rank_order,
            evidence={
                "routing": "additive evidence-weighted scoring over measured scene conditions",
                "decision_rule": "highest score (tie-break: registry order); constraints enforced before ranking",
                "selected_rank": rank_order.index(selected) if selected in rank_order else None,
                "configuration_id": self.cfg.configuration_id,
            },
        ).to_dict()