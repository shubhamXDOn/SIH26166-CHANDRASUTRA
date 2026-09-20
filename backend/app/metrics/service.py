"""M7 MetricsService — orchestrates the measurement pipeline over M2..M6 artefacts.

States: NOT_STARTED / BLOCKED / RUNNING / COMPLETE / INSUFFICIENT / FAILED.
Prerequisite: an M6 registration run in state COMPLETE. All metric values are
read from real artefacts; blocked stages report NOT_RUN/BLOCKED, never zeros.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend.app.config import rfc3339_now
from backend.app.hardening import atomic_write_json, atomic_write_text
from backend.app.metrics.comparison import build_comparison
from backend.app.metrics.config import (
    METRICS_CONFIGURATION_ID,
    METRICS_CONFIGURATION_VERSION,
    MetricsConfig,
)
from backend.app.metrics.experiment import build_experiment_json
from backend.app.metrics.funnel import collect_funnel_metrics
from backend.app.metrics.manifest import build_metrics_manifest, build_metrics_provenance
from backend.app.metrics.reference import REFERENCE_DATASET
from backend.app.metrics.registration import (
    collect_registration_metrics,
    recompute_metric_records,
    recompute_registration_metrics,
)
from backend.app.metrics.report import build_report_json, build_report_markdown
from backend.app.metrics.schema import as_records
from backend.app.metrics.spatial import collect_spatial_metrics
from backend.app.metrics.states import (
    MetricsBlockCode,
    MetricsRunState,
    MetricCategory,
    MetricStatus,
    ScientificStatus,
)
from backend.app.registration.service import RegistrationService
from backend.app.spatial.service import SpatialService

_VALID_METRICS_CONFIG_IDS = {"MT-M7-001"}


class MetricsService:
    def __init__(
        self,
        data_root: Path,
        m7_cfg: dict | None = None,
        m6_cfg: dict | None = None,
        m5_cfg: dict | None = None,
        m4_defaults: dict | None = None,
    ):
        self._data = data_root
        self._m7_cfg = m7_cfg or {}
        self._m6_cfg = m6_cfg or {}
        self._m5_cfg = m5_cfg or {}
        self._m4_defaults = m4_defaults or {}
        self._derived_rel = self._m7_cfg.get("derived_rel", "derived/metrics")

    # ---------- path discovery -------------------------------------------- #

    def _metrics_root(self) -> Path:
        return self._data / self._derived_rel

    def _registration_run(self, pair_id: str) -> Path | None:
        svc = RegistrationService(
            self._data, m6_cfg=self._m6_cfg, m5_cfg=self._m5_cfg, m4_defaults=self._m4_defaults)
        return svc.find_run_for_pair(pair_id)

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        pair_metrics = self._metrics_root() / pair_id
        if not pair_metrics.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_metrics.iterdir()):
            if not proc_dir.is_dir():
                continue
            for matcher_dir in sorted(proc_dir.iterdir()):
                if not matcher_dir.is_dir():
                    continue
                for trust_dir in sorted(matcher_dir.iterdir()):
                    if not trust_dir.is_dir():
                        continue
                    for spatial_dir in sorted(trust_dir.iterdir()):
                        if not spatial_dir.is_dir():
                            continue
                        for rg_dir in sorted(spatial_dir.iterdir()):
                            if not rg_dir.is_dir():
                                continue
                            for mt_dir in sorted(rg_dir.iterdir()):
                                if mt_dir.is_dir():
                                    deepest = mt_dir
        return deepest

    def _resolve_stage_dirs(self, pair_id: str, m6_run: Path) -> dict:
        parts = m6_run.relative_to(self._data).parts
        pair = parts[2]
        pc, mk, tg, sr, rg = parts[3], parts[4], parts[5], parts[6], parts[7]
        return {
            "m2": self._data / "derived" / "processing" / pair / pc,
            "m3": self._data / "derived" / "matches" / pair / pc / mk,
            "m4": self._data / "derived" / "trust" / pair / pc / mk / tg,
            "m5": self._data / "derived" / "spatial" / pair / pc / mk / tg / sr,
            "m6": m6_run,
            "pair": pair,
            "proc_cfg": pc,
            "matcher_cfg": mk,
            "trust_cfg": tg,
            "spatial_cfg": sr,
            "registration_cfg": rg,
        }

    def _run_dir_for(self, stages: dict, metrics_config_id: str) -> Path:
        return (self._metrics_root() / stages["pair"] / stages["proc_cfg"] / stages["matcher_cfg"]
                / stages["trust_cfg"] / stages["spatial_cfg"] / stages["registration_cfg"]
                / metrics_config_id)

    # ---------- public read API ------------------------------------------- #

    def read_status(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return self._synthetic_status(pair_id, MetricsRunState.NOT_STARTED)
        path = run_dir / "status.json"
        if not path.is_file():
            return self._synthetic_status(pair_id, MetricsRunState.NOT_STARTED)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return self._synthetic_status(pair_id, MetricsRunState.NOT_STARTED)

    def summary(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "summary.json").is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        return self._read_json(run_dir / "summary.json", {})

    def metrics(self, pair_id: str) -> list[dict]:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "report.json").is_file():
            return []
        report = self._read_json(run_dir / "report.json", {})
        return report.get("metrics") or []

    def metric_by_id(self, pair_id: str, metric_id: str) -> dict:
        for m in self.metrics(pair_id):
            if m.get("metric_id") == metric_id:
                return m
        return {"error": "NOT_FOUND", "pair_id": pair_id, "metric_id": metric_id}

    def experiment(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "experiment.json").is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        return self._read_json(run_dir / "experiment.json", {})

    def report_json(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "report.json").is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        return self._read_json(run_dir / "report.json", {})

    def report_markdown(self, pair_id: str) -> str:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "report.md").is_file():
            raise FileNotFoundError("No M7 report.md for pair. Run METRICS first.")
        return (run_dir / "report.md").read_text(encoding="utf-8")

    def provenance(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "provenance.json").is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        return self._read_json(run_dir / "provenance.json", {})

    def manifest(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None or not (run_dir / "metrics_manifest.json").is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        return self._read_json(run_dir / "metrics_manifest.json", {})

    def comparison(self, pair_id_a: str, pair_id_b: str) -> dict:
        return build_comparison(pair_id_a, self.metrics(pair_id_a), pair_id_b, self.metrics(pair_id_b))

    # ---------- prerequisites --------------------------------------------- #

    def prerequisites(self, pair_id: str) -> dict:
        m6_run = self._registration_run(pair_id)
        if m6_run is None:
            return {"ready": False, "block_code": MetricsBlockCode.M6_NOT_AVAILABLE.value,
                    "reason": "No M6 registration run exists for this pair — run REGISTRATION first."}
        status_path = m6_run / "status.json"
        if not status_path.is_file():
            return {"ready": False, "block_code": MetricsBlockCode.M6_NOT_AVAILABLE.value,
                    "reason": "M6 status.json missing."}
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ready": False, "block_code": MetricsBlockCode.M6_NOT_AVAILABLE.value,
                    "reason": "M6 status.json unreadable."}
        if status.get("state") != "COMPLETE":
            return {"ready": False, "block_code": MetricsBlockCode.M6_NOT_COMPLETE.value,
                    "reason": f"M6 state is {status.get('state')}, expected COMPLETE.",
                    "m6_state": status.get("state")}
        missing = [name for name in ("diagnostics.json", "transform.json", "validation.json",
                                     "summary.json", "provenance.json")
                   if not (m6_run / name).is_file()]
        if missing:
            return {"ready": False, "block_code": MetricsBlockCode.REGISTRATION_ARTIFACTS_MISSING.value,
                    "reason": f"M6 artefacts missing: {missing}"}
        stages = self._resolve_stage_dirs(pair_id, m6_run)
        m5_status = self._read_json(stages["m5"] / "status.json", {})
        return {
            "ready": True,
            "block_code": None,
            "m6_run": m6_run,
            "m5_state": m5_status.get("state"),
            "stages": stages,
        }

    # ---------- run -------------------------------------------------------- #

    def run(self, pair_id: str, metrics_config_id: str = "MT-M7-001") -> dict:
        if metrics_config_id not in _VALID_METRICS_CONFIG_IDS:
            return self._synthetic_status(pair_id, MetricsRunState.BLOCKED,
                                          block_code=MetricsBlockCode.METRICS_UNKNOWN_CONFIG.value)
        prereq = self.prerequisites(pair_id)
        if not prereq["ready"]:
            return self._synthetic_status(pair_id, MetricsRunState.BLOCKED, block_code=prereq["block_code"])
        stages = prereq["stages"]
        run_dir = self._run_dir_for(stages, metrics_config_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        cfg = self._build_config()
        self._write_status(run_dir, pair_id, MetricsRunState.RUNNING, prereq, cfg)

        try:
            collected, recompute = self._collect(stages, pair_id, cfg)
        except ValueError as exc:
            block = (MetricsBlockCode.FORBIDDEN_TERMINOLOGY.value
                     if "forbidden" in str(exc).lower() else MetricsBlockCode.METRICS_FAILED.value)
            self._write_status(run_dir, pair_id, MetricsRunState.FAILED, prereq, cfg,
                               block_code=block,
                               reasons=[str(exc)])
            return self.read_status(pair_id)
        except Exception as exc:  # noqa: BLE001
            self._write_status(run_dir, pair_id, MetricsRunState.FAILED, prereq, cfg,
                               block_code=MetricsBlockCode.METRICS_FAILED.value,
                               reasons=[f"{type(exc).__name__}: {exc}"])
            return self.read_status(pair_id)

        configuration_chain = self._configuration_chain(stages, metrics_config_id, cfg)
        experiment = build_experiment_json(
            pair_id, configuration_chain,
            stages["m3"], stages["m4"], stages["m5"], stages["m6"], self._data)
        validation = self._validation_summary(collected, recompute)

        report = build_report_json(
            experiment=experiment,
            pair_id=pair_id,
            configuration_chain=configuration_chain,
            validation=validation,
            metrics=collected,
            recompute=recompute,
            attrition=self._attrition_dict(collected),
            run_state=MetricsRunState.COMPLETE.value,
        )
        markdown = build_report_markdown(report)

        self._write_json(run_dir / "experiment.json", experiment)
        self._write_json(run_dir / "report.json", report)
        atomic_write_text(run_dir / "report.md", markdown)
        self._write_registration_metrics(run_dir, pair_id, collected)
        self._write_summary(run_dir, pair_id, MetricsRunState.COMPLETE, cfg,
                            experiment["experiment_id"], validation, recompute)
        self._write_json(run_dir / "provenance.json",
                         build_metrics_provenance(
                             pair_id, self._data,
                             metrics_config_id=metrics_config_id,
                             m2_run_dir=stages["m2"], m3_run_dir=stages["m3"],
                             m4_run_dir=stages["m4"], m5_run_dir=stages["m5"],
                             m6_run_dir=stages["m6"], m7_run_dir=run_dir))
        self._write_json(run_dir / "metrics_manifest.json",
                         build_metrics_manifest(pair_id, metrics_config_id,
                                                cfg.metrics_configuration_version, run_dir, self._data))
        self._write_status(run_dir, pair_id, MetricsRunState.COMPLETE, prereq, cfg)
        return self.read_status(pair_id)

    # ---------- reset ------------------------------------------------------ #

    def reset(self, pair_id: str) -> dict:
        pair_metrics = self._metrics_root() / pair_id
        if pair_metrics.is_dir():
            shutil.rmtree(pair_metrics, ignore_errors=True)
        return self.read_status(pair_id)

    # ---------- internals -------------------------------------------------- #

    def _build_config(self) -> MetricsConfig:
        merged = dict(self._m7_cfg.get("defaults") or {})
        merged.setdefault("metrics_configuration_id",
                          self._m7_cfg.get("metrics_configuration_id", METRICS_CONFIGURATION_ID))
        merged.setdefault("metrics_configuration_version",
                          self._m7_cfg.get("metrics_configuration_version", METRICS_CONFIGURATION_VERSION))
        merged.setdefault("source", self._m7_cfg.get("source", "engineering defaults"))
        merged.setdefault("scientifically_tuned", self._m7_cfg.get("scientifically_tuned", False))
        return MetricsConfig.from_dict(merged)

    def _collect(self, stages: dict, pair_id: str, cfg: MetricsConfig) -> tuple[list[dict], dict]:
        records = []
        records += collect_funnel_metrics(stages["m3"], stages["m4"], stages["m5"], stages["m6"], self._data)
        records += collect_spatial_metrics(stages["m5"], self._data)
        records += collect_registration_metrics(stages["m6"], self._data)

        spatial_svc = SpatialService(self._data, m5_cfg=self._m5_cfg, m4_defaults=self._m4_defaults)
        recompute = recompute_registration_metrics(
            self._data, pair_id, stages["m5"], stages["m6"], cfg, spatial_svc)
        records += recompute_metric_records(recompute)

        records += self._reference_metrics()

        records = as_records(records)
        self._validate_taxonomy(records)
        return records, recompute

    def _reference_metrics(self) -> list[dict]:
        from backend.app.metrics.schema import metric
        return [
            metric(
                "PHYSICAL_TRUTH_AVAILABLE", "physical truth dataset availability", None, None,
                MetricCategory.REFERENCE, "M7", None,
                "reference_dataset_status()",
                "Whether an external physical-truth/reference dataset is integrated (NOT_AVAILABLE at M7).",
                ScientificStatus.REFERENCE, status=MetricStatus.REFERENCE_UNAVAILABLE),
            metric(
                "PHYSICAL_ACCURACY", "physical alignment accuracy", None, None,
                MetricCategory.REFERENCE, "M7", None,
                "policy: never computed without a reference dataset",
                "NOT_AVAILABLE by policy; never reported as 0 or 100%. Requires PRADAN reference truth.",
                ScientificStatus.REFERENCE, status=MetricStatus.REFERENCE_UNAVAILABLE),
        ]

    def _validate_taxonomy(self, records: list[dict]) -> None:
        from backend.app.metrics.taxonomy import TAXONOMY
        unknown = sorted({r.get("metric_id") for r in records} - set(TAXONOMY))
        if unknown:
            raise ValueError(f"metrics not in taxonomy: {unknown}")

    @staticmethod
    def _attrition_dict(records: list[dict]) -> dict:
        for m in records:
            if m.get("metric_id") == "ATTENTION_DISTRIBUTION":
                return m.get("value") or {}
        return {}

    @staticmethod
    def _validation_summary(records: list[dict], recompute: dict) -> dict:
        counts = {s.value: 0 for s in MetricStatus}
        for m in records:
            counts[m.get("status", MetricStatus.NOT_RUN.value)] = counts.get(
                m.get("status", MetricStatus.NOT_RUN.value), 0) + 1
        return {
            "metrics_total": len(records),
            "metrics_available": counts[MetricStatus.AVAILABLE.value],
            "metrics_blocked": counts[MetricStatus.BLOCKED.value],
            "metrics_not_run": counts[MetricStatus.NOT_RUN.value],
            "metrics_not_applicable": counts[MetricStatus.NOT_APPLICABLE.value],
            "metrics_insufficient": counts[MetricStatus.INSUFFICIENT.value],
            "metrics_failed": counts[MetricStatus.FAILED.value],
            "metrics_reference_unavailable": counts[MetricStatus.REFERENCE_UNAVAILABLE.value],
            "recomputation_consistent": bool(recompute.get("consistent_with_fit")),
            "recomputation_status": recompute.get("status"),
            "recomputation_mismatch": recompute.get("match_mismatch") or [],
        }

    def _configuration_chain(self, stages: dict, metrics_config_id: str, cfg: MetricsConfig) -> dict:
        source = self._m7_cfg.get("source", "engineering defaults")
        try:
            source = Path(source).name
        except (TypeError, ValueError):
            source = "engineering defaults"
        return {
            "processing_configuration_id": stages["proc_cfg"],
            "matcher_configuration_id": stages["matcher_cfg"],
            "trust_configuration_id": stages["trust_cfg"],
            "spatial_reliability_configuration_id": stages["spatial_cfg"],
            "registration_configuration_id": stages["registration_cfg"],
            "metrics_configuration_id": metrics_config_id,
            "metrics_configuration_version": int(cfg.metrics_configuration_version),
            "source": source,
            "scientifically_tuned": bool(cfg.scientifically_tuned),
        }

    def _write_registration_metrics(self, run_dir: Path, pair_id: str, records: list[dict]) -> None:
        subset = [
            m for m in records
            if m.get("source_milestone") in ("M6", "M7")
            or m.get("metric_id") in ("FUNNEL_M5_TO_M6_RETENTION",)
        ]
        payload = {
            "pair_id": pair_id,
            "metrics": subset,
            "note": "Registration-focused metrics (measurements, not accuracy claims).",
        }
        self._write_json(run_dir / "registration_metrics.json", payload)

    def _write_summary(self, run_dir, pair_id, state, cfg, exp_id, validation, recompute) -> None:
        summary = {
            "pair_id": pair_id,
            "state": state.value,
            "metrics_configuration_id": cfg.metrics_configuration_id,
            "metrics_configuration_version": int(cfg.metrics_configuration_version),
            "experiment_id": exp_id,
            "reference_dataset": REFERENCE_DATASET,
            "metrics_total": validation["metrics_total"],
            "metrics_available": validation["metrics_available"],
            "metrics_blocked": validation["metrics_blocked"],
            "metrics_not_run": validation["metrics_not_run"],
            "metrics_not_applicable": validation["metrics_not_applicable"],
            "metrics_reference_unavailable": validation["metrics_reference_unavailable"],
            "recomputation_consistent": validation["recomputation_consistent"],
            "generated_at": rfc3339_now(),
        }
        self._write_json(run_dir / "summary.json", summary)

    def _write_status(self, run_dir, pair_id, state, prereq=None, cfg=None,
                      block_code=None, reasons=None) -> None:
        status = {
            "pair_id": pair_id,
            "state": state.value,
            "metrics_configuration_id": cfg.metrics_configuration_id if cfg else METRICS_CONFIGURATION_ID,
            "metrics_configuration_version": int(cfg.metrics_configuration_version if cfg else METRICS_CONFIGURATION_VERSION),
            "block_code": block_code,
            "reasons": reasons or [],
            "scientific_note": "Metrics are measurements of pipeline evidence, never proof of physical truth.",
            "updated_at": rfc3339_now(),
        }
        if prereq and prereq.get("ready"):
            status["input_chain"] = {
                "processing_configuration_id": prereq["stages"]["proc_cfg"],
                "matcher_configuration_id": prereq["stages"]["matcher_cfg"],
                "trust_configuration_id": prereq["stages"]["trust_cfg"],
                "spatial_reliability_configuration_id": prereq["stages"]["spatial_cfg"],
                "registration_configuration_id": prereq["stages"]["registration_cfg"],
            }
        self._write_json(run_dir / "status.json", status)

    def _synthetic_status(self, pair_id, state, block_code=None, reasons=None) -> dict:
        return {
            "pair_id": pair_id,
            "state": state.value,
            "metrics_configuration_id": METRICS_CONFIGURATION_ID,
            "block_code": block_code,
            "reasons": reasons or [],
            "updated_at": rfc3339_now(),
        }

    def _read_json(self, path: Path, fallback):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return fallback

    def _write_json(self, path: Path, payload) -> None:
        atomic_write_json(path, payload)

    def reset_run(self, pair_id: str) -> dict:
        return self.reset(pair_id)