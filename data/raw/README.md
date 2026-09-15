# data/raw — IMMUTABLE

This tree holds **raw, unmodified** scientific data only.

- OHRC   -> data/raw/ohrc/     (CH-2 Orbiter High Resolution Camera, ~0.25 m/px)
- TMC-2  -> data/raw/tmc2/     (CH-2 Terrain Mapping Camera-2, ~5 m/px)
- IIRS   -> data/raw/iirs/
- LROC   -> data/raw/lroc/     (NASA reference/validation layer, later milestones)

Immutable by policy: nothing in this tree is ever rewritten, deleted, or
cached into. All derived products go to `data/derived/`.

## Expected CH-2 product format (M1)

Chandrayaan-2 products are delivered as a **generic binary image** plus a
**detached PDS4 label**. The `.img` is the data; the `.xml` label is its
metadata. CHANDRASUTRA's M1 loader parses the PDS4 label (namespace-agnostic)
to recover product ID, observation time, dimensions, data type, nominal GSD
and flight parameters — it does **not** guess from the binary bytes.

Official naming pattern (used to decode instrument, level and camera):

```
ch2_<instrument>_<phase><type><camera>_<UTC>_<P><product>_<orbit>.<ext>

example (OHRC, derived):  ch2_ohr_ncp_20211228T2209123959_d_img_d18.img
example (TMC-2):          ch2_tmc_ncn_20200207T0716469418_d_img_d18.img
```

- type: `r` = raw, `c` = calibrated, `d` = derived
- camera: `p` = panchromatic, `f`/`n`/`a` = fore / nadir / aft (TMC-2)

Place each downloaded product and its sibling `.xml` label in the matching
sensor directory above, then register the pair through the Data workspace
(which hashes the raw bytes and never touches this tree).

> **Availability (verified 2026):** official downloads require a PRADAN
> account with administrator-approved access
> (https://pradan.issdc.gov.in/ch2/). There is no anonymous bulk path.
> `data/raw/*` intentionally stays empty until real products are downloaded.

Remote downloads happen in M1+ through documented, reproducible commands —
never as ad-hoc copies of unknown provenance.