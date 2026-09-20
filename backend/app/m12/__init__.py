"""M12 — final scientific validation, reproducibility & evidence freeze.

M12 is the science-integrity boundary of CHANDRASUTRA (SIH26166). It does not
add scientific capability; it proves that what M0..M11 produce is coherent,
reproducible and honestly reported. It provides:

    * configuration freeze  (m12.config_freeze)   — committed-config fingerprints
    * raw-data freeze       (m12.raw_integrity)   — SHA-256 re-verification gate
    * provenance chain      (m12.provenance)      — M1..M9 artefact chain + digests
    * independent audits    (m12.audits)          — recomputed candidate funnel,
                                        trust, spatial selection, registration
                                        validation/residuals vs recorded artefacts
    * AI claim validation   (m12.crosscheck)      — evidence-grounded Gemini validator
    * evidence package      (m12.package)         — final_evidence/ + manifest.json
                                        + FINAL_EVIDENCE_SHA256 + frozen-state verify

The two legitimate paths are PATH A (real, authorised, PRADAN-verified raw data
passing the real-data gate) and PATH B (honest BLOCKED state for real data, with
deterministic synthetic TEST_FIXTURE engineering proof, never labelled as real).
"""

from __future__ import annotations

M12_MILESTONE = "M12"
M12_CORPUS_NAME = "tests/test_m12.py"

__all__ = ["M12_MILESTONE", "M12_CORPUS_NAME"]