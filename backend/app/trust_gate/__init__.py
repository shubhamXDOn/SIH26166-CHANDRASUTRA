"""M7 TRUST GATE — Geometric Verification of Candidate Correspondences.

Consumes a single M3/M4/M6 matcher RUN ARTIFACT (candidate correspondences in
their declared coordinate frame), performs conservative, deterministic robust
geometric verification (affine -> homography hierarchy via numpy DLT + seeded
RANSAC, reusing ``backend.app.trust.geometry``), and emits an explicit evidence
bundle with a Trust Gate decision:

    ACCEPT   - verification executed and the predeclared gate is satisfied
    REJECT   - verification executed but the evidence fails the gate
    ABSTAIN  - evidence is insufficient/ambiguous for a trustworthy decision
    BLOCKED  - a required prerequisite is unavailable or invalid

A Trust Gate ACCEPT only means "the correspondence set satisfied the configured
geometric verification criteria". It is never a physical- or registration-
accuracy claim (``reference_status`` stays ``REFERENCE_UNAVAILABLE`` unless
independent reference data is registered). This package never performs M8-style
balanced spatial selection and never performs M9 registration semantics.
"""