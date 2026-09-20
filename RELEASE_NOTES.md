# CHANDRASUTRA — v1.0.0 Release Notes

**Release:** CHANDRASUTRA v1.0.0 (M13 Final Release)
**Project:** SIH26166 — Trustworthy Lunar Image Intelligence
**Engineering build identity:** `0.11.0` (kept fixed: it is the M11 operations
stage identity recorded inside the frozen configuration chain — see below)
**Suggested tag:** `chandrasutra-v1.0.0`

> These notes describe the **engineering proof** presented by this release.
> Real mission validation is still **BLOCKED** on official data access, and the
> system says so honestly throughout. No result in this release is fabricated.

---

## 1. What this is

CHANDRASUTRA is a reliability-first scientific platform for correspondence and
registration of heterogeneous lunar imagery (Chandrayaan-2 OHRC × TMC-2). It is
built around adaptive reliability: condition-aware matcher strategy, independent
geometric verification, measurable diagnostics, immutable raw data and principled
abstention (BLOCKED is a first-class outcome). v1.0.0 freezes the engineering
evidence across milestones M0–M12 and packages it for a jury demonstration.

## 2. What is now frozen (v1.0.0)

| Item | Value | Status |
| --- | --- | --- |
| Frozen experiment | `EXP-EE0EBE7187E5` (pair `CS-P001`) | FROZEN · VERIFIED |
| Final evidence digest (`FINAL_EVIDENCE_SHA256`) | `c8fbab19dee75ce92870755bdf5202ad1402ee97166a8bdbfc3db8dfd7557e37` | VERIFIED |
| Configuration freeze fingerprint | `9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce` | RECORDED |
| Scientific gate | PATH B · `SYNTHETIC_DATA_ONLY` | HONEST |
| Reproducibility | RUN A/B/C byte-identical signatures | REPRODUCIBLE |
| Independent audits | raw-integrity re-computation | VERIFIED |
| AI cross-check | explanatory claims independently validated | CLEAR · 0 violations |
| Security scan of the frozen package | secrets | CLEAN |
| Provenance chain M1–M7 | configuration IDs recorded + hashed artifacts | PARTIAL · HOLD |
| Provenance chain M8–M9 | per-pair deep-matcher run / AI evidence packet | NOT_RUN (honest) |
| Real mission data | official PRADAN access | BLOCKED (PATH B) |
| Reference dataset | none certified | NOT_AVAILABLE |
| Physical accuracy claim | no reference dataset | NOT_CLAIMED |

Engineering determinism proof: the same pair + configuration IDs reproduce the
same funnel (`100 → 84 → 19 → 19`), the same transform matrix hash and the same
metrics report hash across three independent runs.

## 3. What is new in M13

- **Final release surface** — `GET /api/m13/status` (aggregate release stance),
  evidence explorer endpoints, report centre, reproducibility record, honest
  measurements endpoint and a non-destructive `POST /api/m13/demo/reset`.
- **Release presentation in the app** — the Overview is now a jury-facing
  landing (brand lock-up, launch-demonstration and explore-evidence calls to
  action, explicit “synthetic demonstration — not a real observation” marker)
  and a new **Evidence** page shows the frozen package, provenance chain,
  reproducibility record, report centre and release stance.
- **Release docs & tooling** — `DEPLOYMENT.md`, `REAL_DATA_ONBOARDING.md`, this
  file, `release_manifest.json`, `scripts/m13_release_prep.py` (OneDrive-safe
  evidence seeding + re-verification), `scripts/m13_perf.py` (honest local API
  timings), `scripts/m13_ppt_assets.py` (real-number SVG assets),
  `tests/test_m13.py` (B01–B40 release bug-hunt corpus) and
  `M13_FINAL_RELEASE_REPORT.md`.
- **Release identity without breaking science** — the app keeps engineering
  identity `0.11.0`/M11 so the frozen configuration chain (of which
  `app_version` is the M11 stage id) stays byte-identical and
  `VERIFIED`; the *release* version `1.0.0`/M13 is exposed separately and
  never enters the frozen fingerprint.

## 4. Honest status table (read before presenting)

| Question | Answer |
| --- | --- |
| Are results fabricated? | No. |
| Is this real lunar-mission validation? | No — `SYNTHETIC_DATA_ONLY` TEST_FIXTURE pair. |
| Why is real data blocked? | Official PRADAN (ISSDC, Chandrayaan-2) account approval pending; no credentialed download path in this environment. |
| Is physical registration accuracy claimed? | No — no certified reference dataset (`NOT_AVAILABLE`). |
| Is the provenance chain complete? | M1–M7 yes (IDs + hashes); M8/M9 recorded honestly as NOT_RUN; overall **PARTIAL · HOLD**. |
| Is the frozen evidence intact? | Yes — digest re-verified `VERIFIED` at release prep and on every demo reset. |
| Is there a public hosted URL? | No public deployment exists in this environment; hosted latency is `NOT_MEASURED`, never estimated. |
| Configuration fingerprint change | None — the recorded fingerprint is byte-for-byte the released one. |

## 5. Known limitations (unchanged from M12, still true)

- Matcher(s) are explainable, condition-routed heuristics; deep-matcher
  (M8) weights are not present and no per-pair M8 run exists.
- AI explanations (M9) require a configured provider; none is configured in
  the released environment, so M9 evidence packets are `NOT_AVAILABLE`.
- Full end-to-end scientific validation on real OHRC–TMC-2 imagery is pending
  real-data onboarding (see `REAL_DATA_ONBOARDING.md`).

## 6. Getting started at v1.0.0

1. `README.md` — setup, run, test.
2. `DEPLOYMENT.md` — Docker deployment, `.env`, seeding, hosting notes.
3. `REAL_DATA_ONBOARDING.md` — how the real-data gate (PATH A) opens.
4. `M13_FINAL_RELEASE_REPORT.md` — the milestone report with the full status
   matrix and regression numbers.

## 7. Signature block

```
RELEASE              CHANDRASUTRA v1.0.0  (engineering build 0.11.0)
EXPERIMENT           EXP-EE0EBE7187E5
PAIR                 CS-P001
GATE                 PATH B · SYNTHETIC_DATA_ONLY
FINAL EVIDENCE SHA256 c8fbab19dee75ce92870755bdf5202ad1402ee97166a8bdbfc3db8dfd7557e37
CONFIG FINGERPRINT   9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce
REPRODUCIBILITY      REPRODUCIBLE (RUN A/B/C identical)
REAL DATA            BLOCKED · PATH B (PRADAN access pending)
REFERENCE            NOT_AVAILABLE
PROVENANCE           PARTIAL · HOLD (M8/M9 NOT_RUN, not fabricated)
```