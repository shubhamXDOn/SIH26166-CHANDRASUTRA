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


CORRELATED_OHRC = {**OHRC_FIXTURE, "lines": 700, "samples": 520}
CORRELATED_TMC2 = {**TMC2_FIXTURE, "lines": 700, "samples": 540}


def _synthetic_scene_rows(size: int = 800, cols: int = 650, seed: int = 5) -> np.ndarray:
    """A deterministic, structured synthetic lunar-like scene (0..1 float).

    Low-frequency terrain + high-contrast craters; resolution 1 px = 0.5 m.
    Both sensors sample the *same* scene through different sub-windows, so M3
    matching can genuinely localise candidate correspondences — for SOFTWARE
    validation only, never as real imagery.
    """
    rng = np.random.default_rng(seed)
    coarse = rng.uniform(0.15, 0.85, size=(40, 36))
    rows_i = np.linspace(0, coarse.shape[0] - 1, size)
    cols_i = np.linspace(0, coarse.shape[1] - 1, cols)
    base = np.clip(interp2d(coarse, rows_i, cols_i), 0.15, 0.85)

    rng2 = np.random.default_rng(seed + 1)
    for _ in range(seed % 7 + 5):
        cx = rng2.integers(0, cols)
        cy = rng2.integers(0, size)
        r = rng2.uniform(6, 40)
        yy, xx = np.mgrid[0:size, 0:cols]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        rim = np.logical_and(dist >= r * 0.85, dist <= r * 1.1)
        floor = dist <= r * 0.85
        base[rim] = np.minimum(base[rim] + 0.18, 0.99)
        base[floor] = np.maximum(base[floor] - 0.22, 0.03)

    # gentle radiometric gradient across the sensor (sensor response, not truth)
    grad = (np.arange(size)[:, None] / size) * 0.05
    return np.clip(base + grad, 0.03, 0.99)


def interp2d(grid: np.ndarray, rows_i: np.ndarray, cols_i: np.ndarray) -> np.ndarray:
    """Bilinear interpolation of a coarse float grid to a dense (rows, cols) map."""
    r_idx = np.clip(rows_i[:, None].astype(np.int64), 0, grid.shape[0] - 2)
    c_idx = np.clip(cols_i[None, :].astype(np.int64), 0, grid.shape[1] - 2)
    wa = rows_i[:, None] - r_idx
    wb = cols_i[None, :] - c_idx
    top = grid[r_idx, c_idx] * (1 - wb) + grid[r_idx, c_idx + 1] * wb
    bot = grid[r_idx + 1, c_idx] * (1 - wb) + grid[r_idx + 1, c_idx + 1] * wb
    return top * (1 - wa) + bot * wa


def write_correlated_fixtures(root: Path) -> dict:
    """Overwrite the standard fixture products with a correlated synthetic pair.

    Scene windows:
        OHRC (700x520) samples scene rows [50:750), cols [50:570)
        TMC2 (700x540) samples scene rows [25:725), cols [25:565)
    so the shared ground region carries genuinely corresponding features
    (pure translation, matching is scale-neutral here), heavily labelled
    TEST FIXTURE / SYNTHETIC.
    """
    scene = _synthetic_scene_rows(size=800, cols=650, seed=5)
    ohrc_img = (scene[50:50 + CORRELATED_OHRC["lines"], 50:50 + CORRELATED_OHRC["samples"]] * 65535).astype(np.uint16)
    tmc2_img = (scene[25:25 + CORRELATED_TMC2["lines"], 25:25 + CORRELATED_TMC2["samples"]] * 65535).astype(np.uint16)

    rng_a = np.random.default_rng(11)
    rng_b = np.random.default_rng(29)
    ohrc_img = np.clip(ohrc_img.astype(np.int64) + rng_a.normal(0, 350, ohrc_img.shape).astype(np.int64), 0, 65535).astype(np.uint16)
    tmc2_img = np.clip(tmc2_img.astype(np.int64) + 4000 + rng_b.normal(0, 700, tmc2_img.shape).astype(np.int64), 0, 65535).astype(np.uint16)

    def write(fixture: dict, data: np.ndarray) -> tuple[Path, Path]:
        img = root / fixture["dir"] / f"{fixture['stem']}.img"
        lab = root / fixture["dir"] / f"{fixture['stem']}.xml"
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(data.astype(">u2").tobytes())
        lab.write_text(_label_xml(fixture), encoding="utf-8")
        return img, lab

    img_a, lab_a = write(CORRELATED_OHRC, ohrc_img)
    img_b, lab_b = write(CORRELATED_TMC2, tmc2_img)
    return {"ohrc_img": img_a, "ohrc_label": lab_a, "tmc2_img": img_b, "tmc2_label": lab_b}


# --------------------------------------------------------------------------
# REAL-SHAPED structure labels (M1 PATH A software validation)
# --------------------------------------------------------------------------
# These mimic the IDENTIFICATION/GEOMETRY SHAPE of genuine ISRO PRADAN PDS4
# labels (official urn:isro:ch2 namespace, Geographic_Extent bounding boxes,
# Footprint_Geometry vertices, illumination angles, orbit numbers) so the
# real-data intake path can be exercised. They are written ONLY inside pytest
# tmp dirs — never in the repo, never committed, and never usable as science.

OHRC_REAL_SHAPED_BBOX = {"west": 34.0, "east": 34.6, "north": 13.0, "south": 12.5}
TMC2_REAL_SHAPED_BBOX = {"west": 34.2, "east": 34.9, "north": 13.2, "south": 12.6}

OHRC_REAL_SHAPED = {
    "dir": "raw/ohrc",
    "stem": "ch2_ohr_ncp_20211228T2209123959_c_img_d18",
    "product_id": "urn:isro:ch2:ohrc:sci:ch2_ohr_ncp_20211228T2209123959_c_img_d18",
    "lines": 200,
    "samples": 256,
    "dtype": "UnsignedMSB2",
    "numpy_dtype": ">u2",
    "start": "2021-12-28T22:09:12.395Z",
    "stop": "2021-12-28T22:09:13.100Z",
    "title": "Chandrayaan-2 OHRC calibrated image product",
    "description": "Simulated CH-2 product used for software structure validation.",
}

TMC2_REAL_SHAPED = {
    "dir": "raw/tmc2",
    "stem": "ch2_tmc_ncn_20200207T0716469418_c_img_d18",
    "product_id": "urn:isro:ch2:tmc2:sci:ch2_tmc_ncn_20200207T0716469418_c_img_d18",
    "lines": 300,
    "samples": 384,
    "dtype": "UnsignedMSB2",
    "numpy_dtype": ">u2",
    "start": "2020-02-07T07:16:46.418Z",
    "stop": "2020-02-07T07:16:47.200Z",
    "title": "Chandrayaan-2 TMC-2 nadir map image product",
    "description": "Simulated CH-2 product used for software structure validation.",
}


def _real_shaped_label_xml(f: dict, bbox: dict) -> str:
    from textwrap import dedent

    verts = []
    poly = [
        (bbox["south"], bbox["west"]),
        (bbox["south"], bbox["east"]),
        (bbox["north"], bbox["east"]),
        (bbox["north"], bbox["west"]),
    ]
    for lat, lon in poly:
        verts.append(f"          <Vertex unit='deg' latitude='{lat}' longitude='{lon}'>{lat} {lon} 0.0</Vertex>")
    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <Product_Observational xmlns="http://pds.nasa.gov/pds4/pds/v1">
          <Identification_Area>
            <logical_identifier>{f['product_id']}</logical_identifier>
            <title>{f['title']}</title>
            <information_model_version>1.15.0.0</information_model_version>
            <Product_class>Product_Observational</Product_class>
            <Modification_History>
              <Modification_Detail>
                <description>{f['description']}</description>
              </Modification_Detail>
            </Modification_History>
          </Identification_Area>
          <Observation_Area>
            <Time_Coordinates>
              <start_date_time>{f['start']}</start_date_time>
              <stop_date_time>{f['stop']}</stop_date_time>
            </Time_Coordinates>
            <Investigation_Area>
              <name>Chandrayaan-2</name>
            </Investigation_Area>
            <Observing_System>
              <Observing_System_Component>
                <name>Orbiter High Resolution Camera</name>
                <type>Instrument</type>
                <instrument_id>OHRC</instrument_id>
              </Observing_System_Component>
            </Observing_System>
            <Geometry_Header>
              <orbit_number>8842</orbit_number>
              <Geometry_1D_Header>
                <solar_zenith_angle>67.5</solar_zenith_angle>
                <incidence_angle>68.1</incidence_angle>
                <emission_angle>22.4</emission_angle>
                <phase_angle>86.2</phase_angle>
                <sensor_azimuth>141.7</sensor_azimuth>
              </Geometry_1D_Header>
            </Geometry_Header>
            <Spatial_Extent>
              <Geographic_Extent>
                <west_bounding_coordinate unit='deg'>{bbox['west']}</west_bounding_coordinate>
                <east_bounding_coordinate unit='deg'>{bbox['east']}</east_bounding_coordinate>
                <north_bounding_coordinate unit='deg'>{bbox['north']}</north_bounding_coordinate>
                <south_bounding_coordinate unit='deg'>{bbox['south']}</south_bounding_coordinate>
              </Geographic_Extent>
            </Spatial_Extent>
            <Footprint_Geometry>
              <coordinate_source_type>FOOTPRINT_GENERATION_SYSTEM</coordinate_source_type>
              <Footprint>
                <Footprint_Polygon>
                  <Vertex unit='deg' latitude='0' longitude='0'>0.0 0.0 0.0</Vertex>
    {chr(10).join(verts)}
                </Footprint_Polygon>
              </Footprint>
            </Footprint_Geometry>
          </Observation_Area>
          <File_Area_Observational>
            <File>
              <file_name>{f['stem']}.img</file_name>
              <record_type>UNDEFINED</record_type>
              <encoding_type>BINARY</encoding_type>
            </File>
            <Array_2D>
              <offset unit="byte">0</offset>
              <axes>2</axes>
              <Axis_Array>
                <axis_name>Line</axis_name>
                <sequence_number>1</sequence_number>
                <elements>{f['lines']}</elements>
              </Axis_Array>
              <Axis_Array>
                <axis_name>Sample</axis_name>
                <sequence_number>2</sequence_number>
                <elements>{f['samples']}</elements>
              </Axis_Array>
              <Element_Array>
                <data_type>{f['dtype']}</data_type>
              </Element_Array>
            </Array_2D>
          </File_Area_Observational>
        </Product_Observational>
        """)


def write_real_shaped_pair(
    root: Path,
    *,
    ohrc_bbox: dict | None = None,
    tmc2_bbox: dict | None = None,
) -> dict:
    """Write a REAL-SHAPED structure pair (both sides urn:isro:ch2 identities).

    Default bounding boxes overlap -> the intake path should derive
    CONFIRMED_OVERLAP. Provide disjoint bboxes to exercise the unconfirmed
    path. These files are for pytest tmp dirs only, never committed.
    """
    ohrc_bbox = ohrc_bbox or OHRC_REAL_SHAPED_BBOX
    tmc2_bbox = tmc2_bbox or TMC2_REAL_SHAPED_BBOX
    img_a = root / OHRC_REAL_SHAPED["dir"] / f"{OHRC_REAL_SHAPED['stem']}.img"
    lab_a = root / OHRC_REAL_SHAPED["dir"] / f"{OHRC_REAL_SHAPED['stem']}.xml"
    img_b = root / TMC2_REAL_SHAPED["dir"] / f"{TMC2_REAL_SHAPED['stem']}.img"
    lab_b = root / TMC2_REAL_SHAPED["dir"] / f"{TMC2_REAL_SHAPED['stem']}.xml"
    img_a.parent.mkdir(parents=True, exist_ok=True)
    img_b.parent.mkdir(parents=True, exist_ok=True)
    img_a.write_bytes(_array_bytes(OHRC_REAL_SHAPED, seed=11))
    img_b.write_bytes(_array_bytes(TMC2_REAL_SHAPED, seed=29))
    lab_a.write_text(_real_shaped_label_xml(OHRC_REAL_SHAPED, ohrc_bbox), encoding="utf-8")
    lab_b.write_text(_real_shaped_label_xml(TMC2_REAL_SHAPED, tmc2_bbox), encoding="utf-8")
    return {"ohrc_img": img_a, "ohrc_label": lab_a, "tmc2_img": img_b, "tmc2_label": lab_b}