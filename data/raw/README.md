# data/raw — IMMUTABLE

This tree holds **raw, unmodified** scientific data only.

- OHRC   -> data/raw/ohrc/
- TMC-2  -> data/raw/tmc2/
- IIRS   -> data/raw/iirs/
- LROC   -> data/raw/lroc/   (reference/validation layer, later milestones)
- PDS4 labels & metadata -> data/metadata/

Immutable by policy: nothing in this tree is ever rewritten, deleted, or
cached into. All derived products go to `data/derived/`.

Remote downloads happen in M1+ through documented, reproducible commands —
never as ad-hoc copies of unknown provenance.