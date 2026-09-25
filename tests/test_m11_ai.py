"""M11 — Full-pipeline AI evidence + assistant (M1..M10, M11-EVIDENCE-001).

Coverage:
    1. FullEvidenceBuilder packet (schema, m1..m10, honest NOT_STARTED) -> 08
    2. Legacy M9 builder untouched (schema/digest contract preserved)     -> 02
    3. ResponseValidator packet-derived milestones/metrics (M1/M9/M10)    -> 06
    4. PromptBuilder M11 task bodies + _fit over m1..m10                  -> 03
    5. Provenance + audit additive fields                                  -> 03
    6. GeminiAssistant full_evidence orchestration (stubbed provider)     -> 05
    7. API endpoints for the seven M11 tasks                              -> 03

The provider is only ever reached through a stubbed transport; no live Gemini
call is made and no key is required.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.ai import (
    AIAnswer,
    AIRequest,
    AIResponse,
    AIServiceState,
    AIServiceStatus,
    AITask,
    EvidenceBuilder,
    FullEvidenceBuilder,
    GeminiAssistant,
    M11_EVIDENCE_SCHEMA_VERSION,
    ResponseValidator,
    ValidationResult,
    canonical_digest,
    is_terminal,
    load_ai_config,
)
from backend.app.ai.audit import AuditRecorder
from backend.app.ai.client import GeminiClient, GeminiResult
from backend.app.ai.config import AIConfig, DEFAULT_POSSIBLE_MILESTONES
from backend.app.ai.prompts import BuiltPrompt, PromptBuilder
from backend.app.ai.provenance import build_m9_provenance, write_m9_provenance
from backend.app.config import Settings
from backend.app.data import ensure_derived_directories

PAIR = "CH2-20211228T0338-S2A-20191209T0410-S2B"

M11_TASKS = (
    "explain-pipeline",
    "summarize-pipeline",
    "explain-trust",
    "explain-spatial",
    "explain-registration",
    "explain-benchmark",
    "explain-abstention",
)


# ===========================================================================
# 1. FullEvidenceBuilder
# ===========================================================================
def test_m11_full_builder_schema_and_keys(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    build = FullEvidenceBuilder(settings, load_ai_config(settings)).build(PAIR)
    assert build.digest.startswith("sha256:")
    assert build.experiment_id is None
    assert build.packet["schema_version"] == "M11-EVIDENCE-001"
    assert build.packet["description"].startswith("Full-pipeline")
    for key in ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"):
        assert key in build.packet, key
    assert set(build.pipeline_state) == {f"M{n}" for n in range(1, 11)}
    assert build.packet["reference"]["status"] == "REFERENCE_UNAVAILABLE"
    assert build.packet["reference"]["metric_id"] == "PHYSICAL_ACCURACY"


def test_m11_full_builder_empty_repo_honest_not_started(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    build = FullEvidenceBuilder(settings, load_ai_config(settings)).build(PAIR)
    # M1 unavailable (pair unregistered); everything else NOT_STARTED/BLOCKED;
    # nothing is ever reported COMPLETED/REGISTERED when nothing ran.
    assert build.pipeline_state["M1"] == "NOT_AVAILABLE"
    for label in ("M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"):
        assert build.pipeline_state[label] not in ("COMPLETED", "REGISTERED", "ACCEPT"), label
        assert build.pipeline_state[label] in ("NOT_STARTED", "NOT_AVAILABLE", "BLOCKED"), label
    assert any("REFERENCE_UNAVAILABLE" in lim for lim in build.limitations)
    assert any("NOT_STARTED" in lim for lim in build.limitations)


def test_m11_full_builder_deterministic_digest(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    cfg = load_ai_config(settings)
    first = FullEvidenceBuilder(settings, cfg).build(PAIR)
    second = FullEvidenceBuilder(settings, cfg).build(PAIR)
    assert first.digest == second.digest
    assert first.packet == second.packet


def test_m11_full_builder_packet_sanitized(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    blob = FullEvidenceBuilder(settings, load_ai_config(settings))
    build = blob.build(PAIR)
    text = json.dumps(build.packet)
    assert "C:\\Users" not in text
    assert "AIza" not in text


def test_m11_full_builder_m1_registry_single_value(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    build = FullEvidenceBuilder(settings, load_ai_config(settings)).build(PAIR)
    m1 = build.packet["m1"]
    assert m1["source_milestone"] == "M1"
    assert m1["status"] in ("REGISTERED", "NOT_AVAILABLE")
    if m1["status"] == "REGISTERED":
        ids = {m["metric_id"] for m in m1["metrics"]}
        assert "PAIR_SENSOR_A" in ids and "PAIR_DATA_SOURCE_GATE" in ids
    else:
        assert m1["metrics"] == []


def test_m11_full_builder_packets_length_bounded(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    build = FullEvidenceBuilder(settings, load_ai_config(settings)).build(PAIR)
    assert len(json.dumps(build.packet)) < 200_000


def test_m11_full_builder_limits_under_fit_budget(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    prompt = PromptBuilder(load_ai_config(settings))
    packet = FullEvidenceBuilder(settings, load_ai_config(settings)).build(PAIR).packet
    built = prompt.build(task="summarize-pipeline", pair_id=PAIR, packet=packet, digest="sha256:x")
    assert "M11-EVIDENCE-001" in built.contents


# ===========================================================================
# 2. Legacy M9 builder untouched
# ===========================================================================
def test_m11_legacy_m9_builder_unchanged(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    legacy = EvidenceBuilder(settings, load_ai_config(settings)).build(PAIR)
    assert legacy.packet["schema_version"] == "M9-EVIDENCE-001"
    assert "m1" not in legacy.packet and "m9" not in legacy.packet
    assert set(legacy.pipeline_state) == {f"M{n}" for n in range(2, 9)}


def test_m11_legacy_m9_digest_stable(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    cfg = load_ai_config(settings)
    a = EvidenceBuilder(settings, cfg).build(PAIR)
    b = EvidenceBuilder(settings, cfg).build(PAIR)
    assert a.digest == b.digest


# ===========================================================================
# 3. ResponseValidator packet-derived milestones/metrics
# ===========================================================================
def _full_packet(settings: Settings) -> dict:
    ensure_derived_directories(settings)
    return FullEvidenceBuilder(settings, load_ai_config(settings)).build(PAIR).packet


def _m11_text(startswith: str = "M1", metric: str | None = None) -> str:
    pkt = {
        "answer": "The pipeline evidence is grounded.",
        "evidence": [
            {
                "claim": "A milestone claim.",
                "source_milestone": startswith,
                "source_metric": metric,
            }
        ],
        "limitations": [],
        "suggested_inspections": [],
    }
    return json.dumps(pkt)


def test_m11_validator_accepts_m1_m9_m10(settings_factory):
    settings = settings_factory()
    packet = _full_packet(settings)
    v = ResponseValidator(load_ai_config(settings))
    for milestone in ("M1", "M9", "M10"):
        assert v.validate(_m11_text(startswith=milestone), packet=packet).ok, milestone


def test_m11_validator_metric_universe_from_packet(settings_factory):
    settings = settings_factory()
    packet = _full_packet(settings)
    v = ResponseValidator(load_ai_config(settings))
    # metrics that always exist in the packet (present even in an empty repo)
    assert v.validate(_m11_text(startswith="M2", metric="M2_STATE"), packet=packet).ok
    assert v.validate(_m11_text(startswith="M10", metric="M10_STATE"), packet=packet).ok


def test_m11_validator_rejects_made_up_metric(settings_factory):
    settings = settings_factory()
    packet = _full_packet(settings)
    v = ResponseValidator(load_ai_config(settings))
    res = v.validate(_m11_text(startswith="M10", metric="MADE_UP_METRIC"), packet=packet)
    assert not res.ok
    assert res.error_code == "UNKNOWN_EVIDENCE_METRIC"


def test_m11_validator_legacy_packet_still_rejects_m1(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    legacy = EvidenceBuilder(settings, load_ai_config(settings)).build(PAIR).packet
    v = ResponseValidator(load_ai_config(settings))
    res = v.validate(_m11_text(startswith="M1", metric=None), packet=legacy)
    assert not res.ok
    assert res.error_code == "UNKNOWN_EVIDENCE_MILESTONE"


def test_m11_validator_unknown_milestone_rejected_for_full_packet(settings_factory):
    settings = settings_factory()
    packet = _full_packet(settings)
    v = ResponseValidator(load_ai_config(settings))
    assert not v.validate(_m11_text(startswith="M99"), packet=packet).ok


# ===========================================================================
# 4. PromptBuilder M11 task bodies + _fit
# ===========================================================================
def test_m11_prompt_builder_all_m11_tasks(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    packet = _full_packet(settings)
    prompt = PromptBuilder(load_ai_config(settings))
    for task in M11_TASKS:
        built = prompt.build(task=task, pair_id=PAIR, packet=packet, digest="sha256:x")
        assert built.task == task
        assert "M11-EVIDENCE-001" in built.contents


def test_m11_prompt_builder_unknown_task_rejected(settings_factory):
    settings = settings_factory()
    prompt = PromptBuilder(load_ai_config(settings))
    with pytest.raises(ValueError):
        prompt.build(task="nope", pair_id=PAIR, packet=_full_packet(settings), digest="sha256:x")


def test_m11_prompt_fit_drops_newest_largest(settings_factory):
    settings = settings_factory(gemini_max_input_chars=1000)  # clamps to tight budget
    ensure_derived_directories(settings)
    cfg = load_ai_config(settings)
    assert cfg.max_input_chars == 1000
    packet = FullEvidenceBuilder(settings, cfg).build(PAIR).packet
    prompt = PromptBuilder(cfg)
    built = prompt.build(task="explain-pipeline", pair_id=PAIR, packet=packet, digest="sha256:x")
    # the tight budget forces _fit to drop the largest optional subtrees
    # (m1..m10 are all scanned; the largest metrics/summary subkeys go first)
    assert built.dropped, "tight budget should drop packet subtrees"
    assert any(part.startswith("m") for part in built.dropped)
    assert len(built.packet_used) <= len(packet)
    assert built.contents.startswith("TASK:")


# ===========================================================================
# 5. Provenance + audit additive fields
# ===========================================================================
def test_m11_provenance_adds_full_pipeline_fields(settings_factory):
    settings = settings_factory()
    cfg = load_ai_config(settings)
    node = build_m9_provenance(
        settings=settings,
        ai_config=cfg,
        pair_id=PAIR,
        request_id="ai-m11-req-1",
        task="explain-pipeline",
        model="gemini",
        experiment_id="EXP-FINAL-x",
        evidence_digest="sha256:abc",
        response_digest="sha256:def",
        status=AIServiceState.COMPLETE.value,
        pipeline_state={"M1": "REGISTERED", "M10": "NOT_STARTED"},
        evidence_packet_schema="M11-EVIDENCE-001",
        source_gate={"value": "BLOCKED"},
        reference_status="REFERENCE_UNAVAILABLE",
        validation_result="PASS",
    )
    assert node["milestone"] == "M9"
    assert node["evidence_schema_version"] == "M11-EVIDENCE-001"
    assert node["source_gate"] == {"value": "BLOCKED"}
    assert node["reference_status"] == "REFERENCE_UNAVAILABLE"
    assert node["validation_result"] == "PASS"
    assert node.get("prompt") is None
    assert node.get("response") is None
    assert "contents" not in node and "question" not in node


def test_m11_audit_adds_digest_and_validation_result(settings_factory):
    settings = settings_factory()
    ensure_derived_directories(settings)
    entry = AuditRecorder(settings).record(
        request_id="ai-m11-req-2",
        pair_id=PAIR,
        task="explain-pipeline",
        experiment_id="EXP-FINAL-x",
        model="gemini",
        prompt_version=load_ai_config(settings).prompt_version,
        evidence_schema_version="M11-EVIDENCE-001",
        status=AIServiceState.COMPLETE.value,
        latency_ms=123.456,
        evidence_digest="sha256:abc",
        validation_result="PASS",
        source_gate={"value": "BLOCKED"},
        reference_status="REFERENCE_UNAVAILABLE",
    )
    assert entry["evidence_schema_version"] == "M11-EVIDENCE-001"
    assert entry["evidence_digest"] == "sha256:abc"
    assert entry["validation_result"] == "PASS"
    assert entry["source_gate"] == {"value": "BLOCKED"}
    assert entry["reference_status"] == "REFERENCE_UNAVAILABLE"
    assert entry.get("prompt") is None and entry.get("response") is None
    assert "contents" not in entry and "question" not in entry


# ===========================================================================
# 6. Service orchestration (stubbed provider)
# ===========================================================================
class _FakeClient:
    def __init__(self, result: GeminiResult):
        self._result = result
        self.calls: list[dict] = []

    def generate(self, *, system: str, contents: str, max_output_tokens: int | None = None) -> GeminiResult:
        self.calls.append({"system": system, "contents": contents})
        return self._result

    def generate_full(self, **kwargs):
        return self.generate(**kwargs)


def _ok_gemini_result(packet: dict) -> GeminiResult:
    allowed: set[str] = set()
    first = None
    for ms in ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10"):
        entry = packet.get(ms)
        if not isinstance(entry, dict):
            continue
        for m in entry.get("metrics", []):
            allowed.add(m.get("metric_id"))
            if first is None and m.get("metric_id"):
                first = {"claim": "A milestone claim.",
                         "source_milestone": ms.upper(), "source_metric": m["metric_id"]}
    mids = list(allowed)[:3]
    refs = [first] if first else []
    if "<none>" in allowed:
        refs = []
    text = json.dumps({
        "answer": "Recorded pipeline evidence is grounded in the packet.",
        "evidence": refs if refs else
                   [{"claim": "No metric is recorded.", "source_milestone": "PIPELINE", "source_metric": None}],
        "limitations": [],
        "suggested_inspections": [],
    })
    return GeminiResult(
        ok=True,
        state=AIServiceState.COMPLETE,
        text=text,
        usage={"input_tokens": 10, "output_tokens": 20, "model": "gemini-fake"},
    )


def test_m11_service_empty_repo_states_in_response(settings_factory):
    settings = settings_factory(gemini_api_key="K")
    ensure_derived_directories(settings)
    assistant = GeminiAssistant(settings)
    packet = FullEvidenceBuilder(settings, assistant.ai_config).build(PAIR).packet
    assistant._client = _FakeClient(_ok_gemini_result(packet))
    out = assistant.execute(task="explain-pipeline", pair_id=PAIR, full_evidence=True)
    assert out["status"] == "COMPLETE"
    assert out["ai"]["evidence_schema_version"] == "M11-EVIDENCE-001"
    assert out["ai"]["full_pipeline"] is True
    assert set(out["evidence_states"]) == {f"M{n}" for n in range(1, 11)}


def test_m11_service_legacy_execute_still_m9(settings_factory):
    settings = settings_factory(gemini_api_key="K")
    ensure_derived_directories(settings)
    assistant = GeminiAssistant(settings)
    packet = EvidenceBuilder(settings, assistant.ai_config).build(PAIR).packet
    assistant._client = _FakeClient(_ok_gemini_result(packet))
    out = assistant.execute(task="explain", pair_id=PAIR)
    assert out["ai"]["evidence_schema_version"] == "M9-EVIDENCE-001"
    assert out["ai"]["full_pipeline"] is False
    assert set(out["evidence_states"]) == {f"M{n}" for n in range(2, 9)}


def test_m11_service_requires_pair_for_full_pipeline(settings_factory):
    from backend.app.errors import ValidationError as BackendValidationError

    settings = settings_factory(gemini_api_key="K")
    ensure_derived_directories(settings)
    assistant = GeminiAssistant(settings)
    with pytest.raises(BackendValidationError):
        assistant.execute(task="explain-pipeline", pair_id="", full_evidence=True)


def test_m11_service_not_configured_honest(settings_factory):
    settings = settings_factory()  # no gemini key
    ensure_derived_directories(settings)
    assistant = GeminiAssistant(settings)
    assert not assistant.configured
    assert assistant.status is AIServiceState.NOT_CONFIGURED


# ===========================================================================
# 7. API endpoints
# ===========================================================================
def test_m11_api_all_task_endpoints_exist(authed_client_factory):
    with authed_client_factory() as client:
        paths = set((client.app.openapi() or {}).get("paths", {}))
        for path in (f"/api/ai/{t}" for t in M11_TASKS):
            assert path in paths, path


def test_m11_api_not_configured_for_full_pipeline(authed_client_factory):
    with authed_client_factory() as client:  # auth on, no gemini key
        for path in (f"/api/ai/{t}" for t in M11_TASKS):
            r = client.post(path, json={"pair_id": PAIR})
            assert r.status_code == 501, path
            assert r.json()["error"]["code"] == "NOT_CONFIGURED", path
            assert "answer" not in r.json(), path


def test_m11_api_status_surface(authed_client_factory):
    with authed_client_factory(gemini_api_key="K") as client:
        data = client.get("/api/ai/status").json()
        assert data["status"] == "READY"
        assert "M11-EVIDENCE-001" in data["evidence_schema_versions"]
        assert data["possible_milestones"] == list(DEFAULT_POSSIBLE_MILESTONES) + ["M1", "M9", "M10"]
        assert data["full_pipeline_supported"] is True


def test_m11_api_full_pipeline_end_to_end(authed_client_factory):
    with authed_client_factory(gemini_api_key="K") as client:
        # stub the underlying assistant provider so no network is used
        from backend.app.api.ai import _assistant

        assistant = _assistant()
        packet = FullEvidenceBuilder(
            assistant._settings, assistant.ai_config
        ).build(PAIR).packet
        assistant._client = _FakeClient(_ok_gemini_result(packet))
        for path in ("/api/ai/explain-pipeline", "/api/ai/summarize-pipeline"):
            r = client.post(path, json={"pair_id": PAIR})
            assert r.status_code == 200, (path, r.text)
            body = r.json()
            assert body["status"] == "COMPLETE"
            assert body["ai"]["evidence_schema_version"] == "M11-EVIDENCE-001"
            assert set(body["evidence_states"]) == {f"M{n}" for n in range(1, 11)}