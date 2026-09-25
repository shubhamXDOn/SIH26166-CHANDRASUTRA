"""M10 metrics/benchmark controller service.

Facade for the read-only benchmark over settled M3..M9 artefacts:

    * ``variants()`` / ``variant_matrix()``    -- the V1..V6 matrix (config)
    * ``run()``                                -- one pair x variant observation,
                                                  persisted immutably
    * ``status()`` / ``prerequisites()``       -- per pair readiness views
    * ``list()`` / ``latest()`` / ``read()``   -- registry reads
    * ``analyze()`` / ``deltas()``             -- descriptive aggregation
    * ``failure_analysis()``                   -- FT-M10-001 breakdown

The controller never runs upstream milestones and never emits accuracy/
geolocation/winner vocabulary.  Reference status is read from the config and
stamped onto every output so no consumer can mistake the benchmark for a
scientifically calibrated verdict.
"""

from __future__ import annotations

import time
from typing import Any

from ..config import Settings, m10_metrics_config
from .aggregation import delta, summarize
from .extraction import FunnelEvidence, read_funnel
from .registry import BenchmarkRegistry
from .schema import build_row
from .states import REFERENCE_UNAVAILABLE
from .taxonomy import classify
from .variants import Variant, variants_from_config

_REGISTRY_ID = "M10-BMK-001"


class M10MetricsService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.config = m10_metrics_config()
        self.registry = BenchmarkRegistry(self.settings)

    # -- configuration views -------------------------------------------------

    def variant_matrix(self) -> list[Variant]:
        cfg_variants = (self.config.get("variants") or {}).get("ids") or []
        return variants_from_config(cfg_variants)

    def variants(self) -> list[dict[str, Any]]:
        return [v.to_dict() for v in self.variant_matrix()]

    def reference_status(self) -> dict[str, Any]:
        ref = self.config.get("reference_status") or {}
        if isinstance(ref, str):
            return {"value": ref}
        return {
            "value": ref.get("value", REFERENCE_UNAVAILABLE),
            "note": ref.get("note", "no calibrated reference data provisioned"),
        }

    def overview(self) -> dict[str, Any]:
        matrix = self.variant_matrix()
        return {
            "m10_metrics_configuration_id": self.config.get("m10_metrics_configuration_id"),
            "metric_definition_version": self.config.get("metric_definition_version"),
            "failure_taxonomy_version": self.config.get("failure_taxonomy_version"),
            "scientifically_tuned": bool(self.config.get("scientifically_tuned")),
            "reference_status": self.reference_status(),
            "variants": [v.to_dict() for v in matrix],
            "registry": _REGISTRY_ID,
            "no_claim": True,
        }

    # -- pair readiness ------------------------------------------------------

    def prerequisites(self, pair_id: str, *, services: dict[str, Any] | None = None) -> dict[str, Any]:
        svc = services or self._default_services()
        ev = read_funnel(self.settings, svc, pair_id)
        missing = ev.earliest_missing()
        return {
            "pair_id": pair_id,
            "reference_status": self.reference_status(),
            "earliest_missing_stage": missing,
            "stages_observed": {
                stage: bool((ev.stages.get(stage) or {}).get("stage_observed"))
                for stage in ev.stages
            },
            "benchmarkable": missing is None,
        }

    # -- running -------------------------------------------------------------

    def run(self, pair_id: str, variant_id: str = "V4", *, services: dict[str, Any] | None = None) -> dict[str, Any]:
        matrix = {v.id: v for v in self.variant_matrix()}
        variant = matrix.get(variant_id)
        if variant is None:
            raise ValueError("unknown variant id %r (expected one of %s)" % (
                variant_id, sorted(matrix)))
        svc = services or self._default_services()
        ev = read_funnel(self.settings, svc, pair_id, variant=variant)
        state = ev.run_state(allow_abstain=True)

        # Availability-gated variants (V2/V3) never produce a registration
        # outcome when their family is not provisioned; they are guarded.
        row_fields = self._row_fields(ev, pair_id)
        if variant.availability != "AVAILABLE":
            state = "BLOCKED"
            row_fields["stage"] = "input_gate"
            row_fields["notes"] = (
                "%s guard: family not provisioned; downstream measured values "
                "are None, never fabricated." % variant.name
            )
        elif variant.is_ablation():
            # Offline ablations describe the funnel WITHOUT the disabled
            # stage; registration remains honestly NOT_RUN.
            if state == "ABSTAIN" or ev.earliest_missing() is not None and ev.earliest_missing()["stage"] == "registration":
                state = "ABSTAIN" if state == "ABSTAIN" else "BLOCKED"
            row_fields["notes"] = (
                "offline %s ablation; registration NOT_RUN by design, "
                "evidenced upstream stages only." % variant.ablation
            )

        row = build_row(pair_id, variant, state=state, **row_fields)
        evidence = ev.model_dump()
        payload = {
            "run_id": "",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "registry": _REGISTRY_ID,
            "pair_id": pair_id,
            "variant_id": variant.id,
            "state": row["state"],
            "stage": row["stage"],
            "evidence": evidence,
            "metrics": {k: row[k] for k in ("candidate_count", "verified_count", "inlier_count",
                                            "selected_count", "registered_count",
                                            "registration_rmse_px", "registration_p95_px")},
            "ablation": row["ablation"],
            "availability": row["availability"],
            "notes": row["notes"],
            "reference_status": self.reference_status(),
            "no_claim": True,
        }
        run_id = self.registry.write(payload)
        rec = self.registry.read(run_id)
        return rec or payload

    def _row_fields(self, ev: FunnelEvidence, pair_id: str) -> dict[str, Any]:
        stages = ev.stages
        m = stages.get("matching") or {}
        t = stages.get("trust_gate") or {}
        s = stages.get("spatial_selection") or {}
        r = stages.get("registration") or {}
        return {
            "stage": r.get("stage") or s.get("stage") or t.get("stage") or m.get("stage") or "input_gate",
            "candidate_count": m.get("candidate_count"),
            "verified_count": t.get("verified_count"),
            "inlier_count": t.get("inlier_count"),
            "selected_count": s.get("selected_count"),
            "registered_count": r.get("registered_count"),
            "registration_rmse_px": r.get("registration_rmse_px"),
            "registration_p95_px": r.get("registration_p95_px"),
            "runtime_ms": None,
            "notes": None,
        }

    # -- registry reads ------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def read(self, run_id: str) -> dict[str, Any] | None:
        return self.registry.read(run_id)

    def latest(self, pair_id: str) -> dict[str, Any] | None:
        return self.registry.latest_for_pair(pair_id)

    # -- descriptive aggregation ---------------------------------------------

    def analyze(self, *, pair_ids: list[str] | None = None) -> dict[str, Any]:
        runs = self.registry.list()
        if pair_ids:
            wanted = set(pair_ids)
            runs = [r for r in runs if r.get("pair_id") in wanted]
        if not runs:
            return {
                "rows": [], "summary": {"row_count": 0, "metrics": {}},
                "reference_status": self.reference_status(),
                "no_claim": True,
            }
        rows: list[dict[str, Any]] = []
        for rec in runs:
            v = {"id": rec.get("variant_id", ""), "name": rec.get("variant_id", "")}
            rows.append(
                build_row(
                    rec.get("pair_id", ""),
                    v,
                    state=rec.get("state"),
                    stage=rec.get("stage", "input_gate"),
                    candidate_count=rec.get("metrics", {}).get("candidate_count"),
                    verified_count=rec.get("metrics", {}).get("verified_count"),
                    inlier_count=rec.get("metrics", {}).get("inlier_count"),
                    selected_count=rec.get("metrics", {}).get("selected_count"),
                    registered_count=rec.get("metrics", {}).get("registered_count"),
                    registration_rmse_px=rec.get("metrics", {}).get("registration_rmse_px"),
                    registration_p95_px=rec.get("metrics", {}).get("registration_p95_px"),
                    notes=rec.get("notes"),
                )
            )
        return {
            "rows": rows,
            "summary": summarize(rows),
            "reference_status": self.reference_status(),
            "no_claim": True,
        }

    def deltas(self, *, pair_ids: list[str] | None = None) -> dict[str, Any]:
        runs = self.registry.list()
        if pair_ids:
            wanted = set(pair_ids)
            runs = [r for r in runs if r.get("pair_id") in wanted]
        baseline = [r for r in runs if r.get("variant_id") == "V1"]
        variants: list[dict[str, Any]] = []
        for vid in ("V1", "V2", "V3", "V4", "V5", "V6"):
            vrows = [r for r in runs if r.get("variant_id") == vid]
            if not vrows:
                continue
            base_rows = [{
                "variant_id": "V1",
                **{k: (b.get("metrics") or {}).get(k) for k in (
                    "candidate_count", "verified_count", "inlier_count", "selected_count",
                    "registered_count", "registration_rmse_px", "registration_p95_px")},
            } for b in baseline]
            var_rows = [{
                "variant_id": vid,
                **{k: (b.get("metrics") or {}).get(k) for k in (
                    "candidate_count", "verified_count", "inlier_count", "selected_count",
                    "registered_count", "registration_rmse_px", "registration_p95_px")},
            } for b in vrows]
            variants.append(delta(base_rows, var_rows, label=vid))
        return {
            "baseline": "V1",
            "scale": "DESCRIPTIVE",
            "delta": variants,
            "reference_status": self.reference_status(),
            "no_claim": True,
        }

    # -- failure taxonomy -----------------------------------------------------

    def failure_analysis(self, *, pair_ids: list[str] | None = None) -> dict[str, Any]:
        runs = self.registry.list()
        if pair_ids:
            wanted = set(pair_ids)
            runs = [r for r in runs if r.get("pair_id") in wanted]
        buckets: dict[str, list[dict[str, Any]]] = {"failed": [], "abstain": []}
        for rec in runs:
            tax = classify(rec.get("state"))
            if not tax:
                continue
            entry = {
                "run_id": rec.get("run_id"),
                "pair_id": rec.get("pair_id"),
                "variant_id": rec.get("variant_id"),
                "state": rec.get("state"),
                "stage": rec.get("stage"),
                **tax,
            }
            buckets[tax["branch"]].append(entry)
        return {
            "root": "REGISTRATION_FAILURE",
            "failed": buckets["failed"],
            "abstain": buckets["abstain"],
            "counts": {
                "failed": len(buckets["failed"]),
                "abstain": len(buckets["abstain"]),
            },
            "policy": (
                "A failed run never abstains and an abstaining run never "
                "fails; a blocked run is never recorded as an outcome."
            ),
            "reference_status": self.reference_status(),
            "no_claim": True,
        }

    # -- helpers --------------------------------------------------------------

    def _default_services(self) -> dict[str, Any]:
        """Lazily build read-only service accessors for the M3..M9 layers.

        Construction is defensive: any milestone that fails to import simply
        stays unavailable, and the funnel then reports that stage as not
        observed (never as a fabricated value).
        """
        svc: dict[str, Any] = {}

        def _try(milestone: str, module_path: str, attr: str) -> None:
            try:
                import importlib
                mod = importlib.import_module(module_path)
                svc[milestone] = getattr(mod, attr)(self.settings)
            except Exception:
                return

        _try("matching", "backend.app.matching.service", "MatchingService")
        _try("trust", "backend.app.trust_gate.service", "TrustGateService")
        _try("spatial", "backend.app.spatial_m8.service", "SpatialSelectionService")
        _try("registration", "backend.app.registration_m9.service", "RegistrationM9Service")
        return svc