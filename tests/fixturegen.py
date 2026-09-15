"""Synthetic TEST FIXTURES for CHANDRASUTRA M1 software validation.

These are NOT scientific data. They mimic the *structure* of the ISRO PDS4
archive (generic binary ``.img`` + detached ``.xml`` label, official naming
convention) so the loader/registry/validation logic is exercised against
realistic inputs without committing real mission data into Git.

Every label explicitly marks itself: TEST FIXTURE — SYNTHETIC.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

FIXTURE_TAG = "TEST FIXTURE - SYNTHETIC - NOT REAL MISSION DATA - SOFTWARE VALIDATION ONLY"

# Official-naming products mimicking an OHRC (calibrated pan) and a
# TMC-2 (calibrated nadir) imagette.
OHRC_FIXTURE = {
    "dir": "raw/ohrc",
    "stem": "ch2_ohr_ncp_20211228T2209123959_d_img_d18",
    "product_id": "urn:fixture:ch2:ohrc:ch2_ohr_ncp_20211228T2209123959_d_img_d18",
    "lines": 200,
    "samples": 256,
    "dtype": "UnsignedMSB2",
    "numpy_dtype": ">u2",
    "start": "2021-12-28T22:09:12.395Z",
    "stop": "2021-12-28T22:09:13.100Z",
    "title": "SYNTHETIC OHRC imagette",
}

TMC2_FIXTURE = {
    "dir": "raw/tmc2",
    "stem": "ch2_tmc_ncn_20200207T0716469418_d_img_d18",
    "product_id": "urn:fixture:ch2:tmc2:ch2_tmc_ncn_20200207T0716469418_d_img_d18",
    "lines": 300,
    "samples": 384,
    "dtype": "UnsignedMSB2",
    "numpy_dtype": ">u2",
    "start": "2020-02-07T07:16:46.418Z",
    "stop": "2020-02-07T07:16:47.200Z",
    "title": "SYNTHETIC TMC-2 imagette",
}


def _array_bytes(fixture: dict, seed: int = 7) -> bytes:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 65535, size=(fixture["lines"], fixture["samples"]), dtype=np.uint16)
    return arr.astype(fixture["numpy_dtype"]).tobytes()


def _label_xml(fixture: dict) -> str:
    p = fixture
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Product_Observational xmlns="http://pds.nasa.gov/pds4/pds/v1">
  <Identification_Area>
    <logical_identifier>{p['product_id']}</logical_identifier>
    <title>{FIXTURE_TAG} — {p['title']}</title>
    <information_model_version>1.15.0.0</information_model_version>
    <Product_class>Product_Observational</Product_class>
    <Modification_History>
      <Modification_Detail>
        <description>{FIXTURE_TAG}</description>
      </Modification_Detail>
    </Modification_History>
  </Identification_Area>
  <Observation_Area>
    <Time_Coordinates>
      <start_date_time>{p['start']}</start_date_time>
      <stop_date_time>{p['stop']}</stop_date_time>
    </Time_Coordinates>
  </Observation_Area>
  <File_Area_Observational>
    <File>
      <file_name>{p['stem']}.img</file_name>
      <record_type>UNDEFINED</record_type>
      <encoding_type>BINARY</encoding_type>
    </File>
    <Array_2D>
      <offset unit="byte">0</offset>
      <axes>2</axes>
      <Axis_Array>
        <axis_name>Line</axis_name>
        <sequence_number>1</sequence_number>
        <elements>{p['lines']}</elements>
      </Axis_Array>
      <Axis_Array>
        <axis_name>Sample</axis_name>
        <sequence_number>2</sequence_number>
        <elements>{p['samples']}</elements>
      </Axis_Array>
      <Element_Array>
        <data_type>{p['dtype']}</data_type>
      </Element_Array>
    </Array_2D>
  </File_Area_Observational>
</Product_Observational>
"""


def _write_product(root: Path, fixture: dict, *, seed: int = 7, corrupt: bool = False,
                   missing_label: bool = False) -> tuple[Path, Path]:
    img = root / fixture["dir"] / f"{fixture['stem']}.img"
    lab = root / fixture["dir"] / f"{fixture['stem']}.xml"
    img.parent.mkdir(parents=True, exist_ok=True)
    data = _array_bytes(fixture, seed=seed)
    if corrupt:
        data = data[: len(data) // 2]  # truncated -> smaller than label geometry
    img.write_bytes(data)
    if not missing_label:
        lab.write_text(_label_xml(fixture), encoding="utf-8")
    return img, lab


def write_standard_fixtures(root: Path, *, corrupt_a: bool = False, corrupt_b: bool = False,
                            missing_label_a: bool = False, missing_label_b: bool = False) -> dict:
    """Write the standard OHRC + TMC-2 fixture pair and return {side: paths}."""
    img_a, lab_a = _write_product(root, OHRC_FIXTURE, seed=11, corrupt=corrupt_a,
                                  missing_label=missing_label_a)
    img_b, lab_b = _write_product(root, TMC2_FIXTURE, seed=29, corrupt=corrupt_b,
                                  missing_label=missing_label_b)
    return {
        "ohrc_img": img_a, "ohrc_label": lab_a,
        "tmc2_img": img_b, "tmc2_label": lab_b,
    }


def write_extra_product(root: Path, fixture: dict, *, stem: str | None = None,
                        suffix: str = "") -> tuple[Path, Path]:
    """Write an additional (different) fixture product with a custom stem."""
    clone = dict(fixture)
    stem = stem or f"{fixture['stem']}{suffix}"
    clone["stem"] = stem
    clone["product_id"] = f"urn:fixture:ch2:{stem}"
    img, lab = _write_product(root, clone, seed=3)
    return img, lab