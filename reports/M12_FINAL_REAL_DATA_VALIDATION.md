# M12 — Final Real-Data Validation (CASE B)

**Experiment ID:** `EXP-FINAL-SYNTHETIC_STRUCTURAL-53b50b49`
**Status:** REPOSITORY_FREEZE
**Reference status:** `REFERENCE_UNAVAILABLE`
**Updated:** 2026-09-23

## 1. Data gate (real PRADAN data)

`scripts/activate_real_data.py` is our ONLY real-data entry point. It is
invoked, checked for `PATH_A_REAL_DATA` presence, and left **BLOCKED**:

- `PATH_A_REAL_DATA` is not provisioned in this deployment.
- The pipeline and the AI layer therefore honestly report
  `REFERENCE_UNAVAILABLE` and never claim calibrated accuracy or geolocation.
- The user UI shows the AI badge `AI-GROUNDED` only for validator-passed,
  evidence-cited answers; never a fabricated scientific number.

## 2. Final evidence sources

| Source | Role |
| --- | --- |
| `backend/app/ai/evidence_full.py` | M11 full-pipeline packet (M1..M10), schema `M11-EVIDENCE-001` |
| `backend/app/ai/prompts.py` | M11 task bodies, `_fit` over m1..m10 |
| `backend/app/ai/validator.py` | packet-derived milestones/metrics (M1/M9/M10 legality) |
| `backend/app/ai/service.py` | `full_evidence` orchestration + additive status surface |
| `backend/app/api/ai.py` | seven M11 endpoint routes |
| `tests/test_m11_ai.py` | 27 M11 AI tests |

Commitments: evidence-grounded answers only; unrun milestones reported
`NOT_STARTED`; reference status honest `REFERENCE_UNAVAILABLE`.

## 3. Reproducibility

`data/metadata/final/final_experiment.json` pins the experiment identity
(`EXP-FINAL-SYNTHETIC_STRUCTURAL-53b50b49`) and content-hash short. The
M11 packet is deterministic: identical pipeline state ⇒ identical
`sha256:` digest (verified by `test_m11_full_builder_deterministic_digest`).

## 4. Validation summary

| Area | Result |
| --- | --- |
| M11 full-builder packet (schema, keys, honest states) | PASS |
| Legacy M9 builder/digest untouched | PASS |
| Validator M1/M9/M10 + packet metric universe | PASS |
| M11 prompt tasks + fit | PASS |
| Provenance/audit additive fields | PASS |
| Service full_evidence + legacy path | PASS |
| Seven API endpoints registered | PASS |
| Frontend production build | PASS |

Honest-knowledge limitation: real-data accuracy cannot be validated (CASE B);
the `BLOCK`/`ABSTAIN` and `REFERENCE_UNAVAILABLE` vocabulary is the only
honest posture until real PRADAN imagery is provisioned.