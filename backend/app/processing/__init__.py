"""M2 — Trustworthy Preprocessing & Lunar Scene Conditioning (SIH26166).

Purpose and honesty contract:
    * Explicit, configurable, reproducible, non-destructive and inspectable
      preprocessing registered under a Configuration ID (e.g. PC-M2-001).
    * Everything the pipeline does is data-driven and observable through
      ``processing_status.json``, ``processing_manifest.json`` and per-step
      derived artifacts. Nothing is silent, nothing is "repaired".
    * Normalization is DISPLAY-only; radiometric calibration is reported
      NOT_APPLICABLE unless calibration metadata exists.
    * Overlap/crop machinery is real and testable, but M2 labels carry no
      camera model / ground geometry, so REAL pairs block at overlap prep
      with an explicit reason. TEST_FIXTURE geometry (clearly labelled
      synthetic) exercises the full path in software tests only.
    * matcher-readiness is a contract (requirements + tile/condition
      evidence), never a hidden heuristic.
"""