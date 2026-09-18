"""M8 — Deep Matcher Benchmarking, Adaptive Expansion & Trustworthy Matcher Selection.

M8 is the deep-matching expansion layer on top of the working M2->M7 evidence
chain. It NEVER replaces the classical pipeline; it makes deep matching a
measurable, optional, evidence-producing component:

    CONDITION -> ROUTING -> MATCHER -> CANDIDATES -> TRUST GATE
    -> SPATIAL RELIABILITY -> REGISTRATION -> METRICS

M8 consumes M3 routing/condition information and produces candidate
correspondences that remain subject to M4-M7 verification. Deep matcher
confidence is an observation, never a scientific truth verdict.
"""