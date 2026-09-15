"""Real Chandrayaan-2 product loader (M1).

Minimal, honest implementation for the actual product representation
encountered in the ISSDC PRADAN Chandrayaan-2 archive:

    * a generic binary data file (``.img``) plus a detached PDS4 label
      (``.xml``) following the official naming convention
        ch2_<inst>_<phase><type><cam>_<UTC>_<kind>_<station>.<ext>
      e.g. ch2_ohr_ncp_20211228T2209123959_d_img_d18.img
           ch2_tmc_ncn_20200207T0716469418_d_img_d18.img
    * a browse product (``.jpg``) optionally shipped alongside.
    * common container formats (TIFF/PNG/JPEG) for test fixtures.

Scope rule (M1): only what the selected pair needs. No universal PDS4
framework. This module never writes into data/raw and never modifies the
original bytes. Products that cannot be read fail loudly and structurally
(``status: FAILURE``), never silently repaired.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .config import Settings

# --- PDS4 primitive <-> numpy dtype mapping --------------------------------
PDS4_DTYPES: dict[str, np.dtype] = {
    "UnsignedByte": np.dtype("u1"),
    "SignedByte": np.dtype("i1"),
    "SignedLSB2": np.dtype("<i2"),
    "UnsignedLSB2": np.dtype("<u2"),
    "SignedMSB2": np.dtype(">i2"),
    "UnsignedMSB2": np.dtype(">u2"),
    "SignedLSB4": np.dtype("<i4"),
    "UnsignedLSB4": np.dtype("<u4"),
    "SignedMSB4": np.dtype(">i4"),
    "UnsignedMSB4": np.dtype(">u4"),
    "IEEE754LSBSingle": np.dtype("<f4"),
    "IEEE754MSBSingle": np.dtype(">f4"),
    "IEEE754LSBDouble": np.dtype("<f8"),
    "IEEE754MSBDouble": np.dtype(">f8"),
}

# Nominal (sensor capability) GSD from the official Chandrayaan-2 archive
# descriptions — used ONLY as a nominal fallback and always labelled as such.
SENSOR_NOMINAL_GSD_M: dict[str, str] = {
    "ohrc": "0.25",   # ~30 cm at 100 km orbit; PRADAN instrument description
    "tmc2": "5.0",    # TMC-2 nadir GSD at 100 km; PRADAN instrument description
}

UNKNOWN = "UNKNOWN"


class ProductReadError(Exception):
    """Raised when a product cannot be opened or read. Never silently repaired."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


# --------------------------------------------------------------------------
# CH-2 filename convention decoding
# --------------------------------------------------------------------------

def decode_ch2_filename(name: str) -> dict:
    """Decode an official CH-2 product filename into its documented segments.

    Convention (ISRO PDS4 archive):
        ch2_<inst>_<phase><type><cam>_<UTC>_<P><prd>_<station>.<ext>
    Where <phase> = mission phase, <type> = raw/calibrated/derived,
    <cam> = camera/band. Returns a dict with UNKNOWN placeholders when the
    name does not follow the convention (e.g. user-supplied names).
    """
    base = Path(name).name
    parts = base.split(".")
    stem = ".".join(parts[:-1])
    ext = parts[-1].lower() if len(parts) > 1 else ""
    seg = stem.split("_")
    result: dict = {
        "filename": base,
        "stem": stem,
        "extension": ext,
        "conforms": False,
        "mission": UNKNOWN,
        "instrument": UNKNOWN,
        "phase": UNKNOWN,
        "data_type": UNKNOWN,
        "camera": UNKNOWN,
        "acquisition_utc": UNKNOWN,
        "product_kind": UNKNOWN,
        "product_name": UNKNOWN,
        "station": UNKNOWN,
    }
    if len(seg) >= 7 and seg[0] == "ch2":
        result.update(
            conforms=True,
            mission=seg[0],
            instrument=seg[1],
            phase=seg[2][0] if len(seg[2]) >= 1 else UNKNOWN,
            data_type=seg[2][1] if len(seg[2]) >= 2 else UNKNOWN,
            camera=seg[2][2] if len(seg[2]) >= 3 else UNKNOWN,
            acquisition_utc=seg[3],
            product_kind=seg[4],
            product_name=seg[5],
            station=seg[6],
        )
    return result


def data_type_label(data_type: str) -> str:
    """Human label for the CH-2 data type segment (r/c/d)."""
    return {
        "r": "raw",
        "c": "calibrated",
        "d": "derived",
    }.get(data_type, UNKNOWN)


def instrument_short(instrument: str) -> str:
    """Map CH-2 instrument segment to a stable app id."""
    return {
        "ohr": "ohrc",
        "tmc": "tmc2",
        "iirs": "iirs",
    }.get(instrument, instrument)


DRIVE_EXT_PRODUCT_NAMES = {
    "ohrc": {"img": "Image", "brw": "Browse", "grd": "Gridded"},
    "tmc2": {"img": "Image", "brw": "Browse", "dtm": "Digital Terrain Model", "oth": "Orthoimage", "grd": "Gridded"},
}


# --------------------------------------------------------------------------
# Minimal PDS4 label parsing
# --------------------------------------------------------------------------

def _localname(tag: str) -> str:
    """Strip XML namespace from a tag -> local name (namespace-agnostic)."""
    return tag.rsplit("}", 1)[-1]


def _find_first_text(elem: ET.Element, local: str) -> str | None:
    for child in elem.iter():
        if _localname(child.tag) == local and child.text and child.text.strip():
            return child.text.strip()
    return None


def parse_pds4_label(label_path: Path) -> dict:
    """Extract a minimal, honest metadata subset from a PDS4 label.

    Only standard PDS4 elements that actually appear in CH-2 labels are read.
    Anything absent is reported as UNKNOWN — never guessed.
    """
    root = ET.parse(str(label_path)).getroot()
    local_root = _localname(root.tag)

    def g(name: str) -> str:
        return _find_first_text(root, name) or UNKNOWN

    # --- Array_2D / Array_3D core ------------------------------------------
    array = None
    for candidate in root.iter():
        if _localname(candidate.tag) in ("Array_2D", "Array_3D"):
            array = candidate
            break
    array_shape: dict[str, int] = {"lines": UNKNOWN, "samples": UNKNOWN, "bands": 1}
    data_type = UNKNOWN
    offset_bytes = 0
    if array is not None:
        array_type = _localname(array.tag)
        axes = [child for child in array if _localname(child.tag) == "Axis_Array"]
        if array_type == "Array_3D":
            # boxes/bands first, then lines, then samples
            renamed = ["bands", "lines", "samples"]
        else:
            renamed = ["lines", "samples"]
        for i, axis in enumerate(axes[: len(renamed)]):
            size_v = None
            for c in axis.iter():
                if _localname(c.tag) == "elements" and c.text and c.text.strip():
                    try:
                        size_v = int(c.text.strip())
                    except ValueError:
                        pass
                    break
            if size_v is not None:
                array_shape[renamed[i]] = size_v
        data_type = UNKNOWN
        for c in array.iter():
            if _localname(c.tag) == "data_type" and c.text:
                data_type = c.text.strip()
                break
        for c in array.iter():
            if _localname(c.tag) == "offset" and c.text and c.text.strip():
                try:
                    offset_bytes = int(c.text.strip())
                except ValueError:
                    pass
                break

    # --- acquisition time ---------------------------------------------------
    start_utc = g("start_date_time")
    stop_utc = g("stop_date_time")

    # --- identification / attribution --------------------------------------
    lid = g("logical_identifier")
    title = g("title")
    description = g("description")
    instrument_host = g("name")
    instrument = UNKNOWN
    for tag in ("instrument_id", "local_identifier"):
        v = _find_first_text(root, tag)
        if v and v != UNKNOWN:
            instrument = v
            break

    # --- processing / purpose ----------------------------------------------
    purpose = g("purpose")
    processing_level = UNKNOWN
    for tag in ("processing_level", "product_type_id", "Science_Facets"):
        v = _find_first_text(root, tag)
        if v and v != "-" and v != UNKNOWN:
            processing_level = v
            break

    # --- geometry / sampling information (only if actually present) --------
    gsd = None
    for tag in ("sampling_factor", "ground_sample_distance", "pixel_size", "sample_rate"):
        v = _find_first_text(root, tag)
        if v and v != "-":
            try:
                float(v)
                gsd = v
            except ValueError:
                pass
            if gsd:
                break
    footprint = UNKNOWN
    for tag in ("spatial_coverage", "target_name", "min_latitude", "max_latitude"):
        v = _find_first_text(root, tag)
        if v:
            footprint = v
            break
    illumination = UNKNOWN
    for tag in ("solar_zenith_angle", "solar_elevation_angle", "incidence_angle"):
        v = _find_first_text(root, tag)
        if v:
            illumination = v
            break

    return {
        "label_filename": label_path.name,
        "product_class": local_root,
        "logical_identifier": lid,
        "title": title,
        "description": description if description and description != "-" else None,
        "instrument_host": instrument_host if instrument_host != "-" else UNKNOWN,
        "instrument": instrument,
        "array_type": _localname(array.tag) if array is not None else UNKNOWN,
        "lines": array_shape["lines"],
        "samples": array_shape["samples"],
        "bands": array_shape["bands"],
        "data_type": data_type,
        "offset_bytes": offset_bytes,
        "start_date_time": start_utc,
        "stop_date_time": stop_utc,
        "purpose": purpose,
        "processing_level": processing_level,
        "gsd": gsd,          # None when absent
        "footprint": footprint if footprint not in (None, "UNKNOWN") else None,
        "illumination": illumination if illumination not in (None, "UNKNOWN") else None,
        "local_identifier": instrument if instrument else UNKNOWN,
        "sampling_nominal": UNKNOWN,
    }


# --------------------------------------------------------------------------
# Generic binary array reading
# --------------------------------------------------------------------------

def expected_dtype(data_type: str) -> np.dtype:
    try:
        return PDS4_DTYPES[data_type]
    except KeyError:
        raise ProductReadError(
            "DTYPE_UNSUPPORTED",
            f"PDS4 data_type '{data_type}' is not supported yet.",
            {"data_type": data_type},
        )


def open_array(path: Path, meta: dict) -> np.ndarray:
    """Open a linear generic-binary array as a lazy memmap (no full load).

    Uses label-provided shape/dtype/offset only. Raises ProductReadError with
    a *structured* failure when anything is inconsistent — nothing is silent.
    """
    dtype = expected_dtype(meta.get("data_type", ""))
    lines = meta.get("lines")
    samples = meta.get("samples")
    if not isinstance(lines, int) or not isinstance(samples, int):
        raise ProductReadError(
            "PRODUCT_READ_FAILED",
            "Label has no usable Line/Sample geometry for this product.",
            {"lines": lines, "samples": samples},
        )
    bands = meta.get("bands", 1)
    offset = int(meta.get("offset_bytes") or 0)

    bytes_per_pixel = dtype.itemsize
    expected_bytes = offset + lines * samples * bands * bytes_per_pixel
    actual_bytes = path.stat().st_size
    if actual_bytes < expected_bytes:
        raise ProductReadError(
            "PRODUCT_READ_FAILED",
            "Data file is smaller than the product geometry in its label.",
            {
                "file_bytes": actual_bytes,
                "expected_bytes": expected_bytes,
                "lines": lines,
                "samples": samples,
                "bands": bands,
                "dtype": meta.get("data_type"),
            },
        )

    try:
        arr = np.memmap(path, mode="r", dtype=dtype, offset=offset, shape=(lines, samples, bands))
    except (ValueError, OSError, IndexError) as exc:
        raise ProductReadError(
            "PRODUCT_READ_FAILED",
            "Could not map the data file to its label geometry.",
            {
                "lines": lines,
                "samples": samples,
                "bands": bands,
                "dtype": meta.get("data_type"),
                "reason": str(exc)[:200],
            },
        ) from exc

    if bands == 1:
        return np.asarray(arr)[:, :, 0]
    return np.asarray(arr)


# --------------------------------------------------------------------------
# Hashing (raw bytes, exactly as stored)
# --------------------------------------------------------------------------

def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Product loading (top level)
# --------------------------------------------------------------------------

@dataclass
class ProductInfo:
    filename: str
    path: str
    size_bytes: int
    raw_sha256: str
    label_filename: str | None
    product_id: str
    product_type: str
    processing_level: str
    instrument: str                    # ohrc | tmc2 | ...
    camera: str
    station: str
    width: int
    height: int
    bands: int
    dtype: str
    bytes_per_pixel: int
    gsd: str
    gsd_source: str                    # label | nominal | NOT_AVAILABLE
    acquisition_datetime: str
    footprint: str
    illumination_info: str
    viewing_geometry_info: str
    metadata: dict
    status: str                        # OK | FAILURE
    error: dict | None
    conforms_naming: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "raw_sha256": self.raw_sha256,
            "label_filename": self.label_filename,
            "product_id": self.product_id,
            "product_type": self.product_type,
            "processing_level": self.processing_level,
            "instrument": self.instrument,
            "camera": self.camera,
            "station": self.station,
            "width": self.width,
            "height": self.height,
            "bands": self.bands,
            "dtype": self.dtype,
            "bytes_per_pixel": self.bytes_per_pixel,
            "gsd": self.gsd,
            "gsd_source": self.gsd_source,
            "acquisition_datetime": self.acquisition_datetime,
            "footprint": self.footprint,
            "illumination_info": self.illumination_info,
            "viewing_geometry_info": self.viewing_geometry_info,
            "metadata": self.metadata,
            "status": self.status,
            "error": self.error,
            "conforms_naming": self.conforms_naming,
            "extra": self.extra,
        }


def failure_info(filename: str, code: str, message: str, details: dict | None = None) -> ProductInfo:
    return ProductInfo(
        filename=filename,
        path=filename,
        size_bytes=0,
        raw_sha256="",
        label_filename=None,
        product_id=UNKNOWN,
        product_type=UNKNOWN,
        processing_level=UNKNOWN,
        instrument=UNKNOWN,
        camera=UNKNOWN,
        station=UNKNOWN,
        width=0,
        height=0,
        bands=0,
        dtype=UNKNOWN,
        bytes_per_pixel=0,
        gsd=UNKNOWN,
        gsd_source=UNKNOWN,
        acquisition_datetime=UNKNOWN,
        footprint=UNKNOWN,
        illumination_info=UNKNOWN,
        viewing_geometry_info=UNKNOWN,
        metadata={},
        status="FAILURE",
        error={"code": code, "message": message, "details": details or {}},
    )


def load_product(image_path: Path, label_path: Path | None = None) -> ProductInfo:
    """Load one real product: metadata + integrity + basic geometry.

    Never writes, never modifies. Failures are structured, not silent.
    """
    meta: dict = {}
    label_name = None
    ext = image_path.suffix.lower()

    if label_path is not None and label_path.is_file():
        try:
            meta = parse_pds4_label(label_path)
            label_name = label_path.name
        except ET.ParseError as exc:
            return failure_info(
                image_path.name,
                "LABEL_PARSE_FAILED",
                "The PDS4 label could not be parsed as XML.",
                {"label": str(label_path), "reason": str(exc)[:200]},
            )
        except OSError as exc:
            return failure_info(
                image_path.name,
                "LABEL_READ_FAILED",
                "The label file could not be read.",
                {"label": str(label_path), "reason": str(exc)[:200]},
            )

    decoded = decode_ch2_filename(image_path.name)
    instrument = instrument_short(decoded["instrument"]) if decoded["conforms"] else UNKNOWN

    try:
        if meta:
            arr = open_array(image_path, meta)
            width = int(meta["samples"])
            height = int(meta["lines"])
            bands = int(meta["bands"])
            dtype_np = expected_dtype(meta["data_type"])
        else:
            arr, width, height, bands, dtype_np = _open_container(image_path)
            meta["data_type"] = dtype_np.name
    except ProductReadError as exc:
        return failure_info(image_path.name, exc.code, exc.message, exc.details)

    # Hash + size of the exact raw bytes.
    try:
        raw_hash = sha256_of(image_path)
        size_bytes = image_path.stat().st_size
    except OSError as exc:
        return failure_info(
            image_path.name,
            "FILE_READ_FAILED",
            "Could not hash/stat the raw file.",
            {"reason": str(exc)[:200]},
        )

    # Processing level from label or naming convention.
    processing_level = meta.get("processing_level") or UNKNOWN
    if processing_level == UNKNOWN and decoded["conforms"]:
        processing_level = data_type_label(decoded["data_type"])

    # GSD: label value when real, else nominal sensor capability (labelled).
    gsd_value = meta.get("gsd")
    gsd = gsd_value if gsd_value else UNKNOWN
    gsd_source = "label" if gsd_value else UNKNOWN
    if gsd == UNKNOWN and instrument in SENSOR_NOMINAL_GSD_M:
        gsd = f"{SENSOR_NOMINAL_GSD_M[instrument]} (nominal, sensor) *"
        gsd_source = "nominal"

    product_id = meta.get("logical_identifier") or (decoded["stem"] if decoded["conforms"] else image_path.stem)
    product_type = meta.get("array_type") if meta.get("array_type") not in (UNKNOWN, None) else (
        "Browse" if ext in (".jpg", ".jpeg", ".png") else "Image"
    )

    return ProductInfo(
        filename=image_path.name,
        path=str(image_path),
        size_bytes=size_bytes,
        raw_sha256=raw_hash,
        label_filename=label_name,
        product_id=product_id,
        product_type=product_type,
        processing_level=processing_level,
        instrument=instrument,
        camera=decoded["camera"],
        station=decoded["station"],
        width=width,
        height=height,
        bands=bands,
        dtype=str(dtype_np),
        bytes_per_pixel=int(dtype_np.itemsize),
        gsd=gsd,
        gsd_source=gsd_source,
        acquisition_datetime=meta.get("start_date_time") or UNKNOWN,
        footprint=meta.get("footprint") or UNKNOWN,
        illumination_info=meta.get("illumination") or UNKNOWN,
        viewing_geometry_info=UNKNOWN,
        metadata={k: v for k, v in meta.items() if v not in (None, "")},
        status="OK",
        error=None,
        conforms_naming=decoded["conforms"],
        extra={
            "title": meta.get("title") or None,
            "description": meta.get("description"),
            "purpose": meta.get("purpose"),
            "instrument_host": meta.get("instrument_host"),
            "start_utc_fragment": decoded["acquisition_utc"],
        },
    )


def _open_container(path: Path) -> tuple[np.ndarray, int, int, int, np.dtype]:
    """Fallback for labelled/container formats used by test fixtures."""
    ext = path.suffix.lower()
    if ext in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
        try:
            from PIL import Image

            with Image.open(path) as im:
                arr = np.asarray(im.convert("L"))
        except Exception as exc:  # noqa: BLE001 - converted to structured error
            raise ProductReadError(
                "PRODUCT_READ_FAILED",
                "Image container could not be decoded.",
                {"reason": str(exc)[:200]},
            ) from exc
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return arr, arr.shape[1], arr.shape[0], 1, arr.dtype
    if ext in (".npy",):
        try:
            arr = np.load(str(path), mmap_mode="r")
        except Exception as exc:  # noqa: BLE001
            raise ProductReadError(
                "PRODUCT_READ_FAILED",
                "NPY container could not be opened.",
                {"reason": str(exc)[:200]},
            ) from exc
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return np.asarray(arr), arr.shape[1], arr.shape[0], 1, arr.dtype
    raise ProductReadError(
        "FORMAT_UNSUPPORTED",
        "No PDS4 label was provided and the file extension is not a recognized container.",
        {"extension": ext},
    )


# --------------------------------------------------------------------------
# Derived previews (never touch raw)
# --------------------------------------------------------------------------

def build_preview(settings: Settings, info: ProductInfo, *, max_width: int = 640) -> Path:
    """Build a downsampled 8-bit preview PNG under data/derived.

    Explicitly derived and reproducible; never replaces the raw file. Returns
    a structured failure Path (raises ProductReadError) when unsafe.
    """
    from PIL import Image

    img_path = Path(info.path)
    out_dir = settings.data_root_path / "derived" / "visualizations" / "previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(info.filename).stem}_preview.png"

    data_type = info.metadata.get("data_type") if info.metadata else None
    meta_shape = info.metadata if info.metadata else {}
    if info.label_filename and isinstance(meta_shape.get("lines"), int):
        arr = open_array(img_path, meta_shape)
    else:
        arr, _w, _h, _b, _d = _open_container(img_path)

    step = max(1, int(round(arr.shape[1] / max_width))) if arr.shape[1] > max_width else 1
    small = arr[::step, ::step]

    flat = np.asarray(small).astype(np.float32)
    lo, hi = np.percentile(flat, [1.0, 99.0])
    if hi - lo < 1e-6:
        hi = lo + 1.0
    norm = np.clip((flat - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)

    Image.fromarray(norm, mode="L").save(out_path, format="PNG")
    return out_path