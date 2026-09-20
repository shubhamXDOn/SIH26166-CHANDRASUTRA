"""M6 registration API (/api/registration).

Verified alignment workspace; diagnostics are measurements, not scientific proof.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import Settings, m4_config, m5_config, m6_config
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..registration.service import RegistrationService
from ..run_guard import guard_run
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep

logger = get_logger(__name__)
router = APIRouter(prefix="/registration", tags=["registration"], dependencies=[Depends(current_user_dep)])

VALID_REGISTRATION_CONFIG_IDS = {"RG-M6-001"}


def _service(settings: Settings) -> RegistrationService:
    return RegistrationService(
        settings.data_root_path,
        m6_cfg=m6_config(),
        m5_cfg=m5_config(),
        m4_defaults=(m4_config().get("defaults") or {}),
    )


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


@router.get("/configurations")
def list_configurations() -> dict:
    cfg = m6_config()
    return {
        "configurations": [
            {
                "registration_configuration_id": cfg.get("registration_configuration_id", "RG-M6-001"),
                "registration_configuration_version": cfg.get("registration_configuration_version", 1),
                "name": cfg.get("name", "Registration Engine, Verified Alignment & Jury-Ready Registration Workspace"),
                "defaults": cfg.get("defaults", {}),
            },
        ],
        "default_registration_configuration_id": "RG-M6-001",
        "valid_registration_configuration_ids": sorted(VALID_REGISTRATION_CONFIG_IDS),
        "note": "Engineering/policy defaults only; no scientifically tuned lunar thresholds exist yet.",
    }


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    root = service._registration_root()
    pairs_total = 0
    pairs_complete = 0
    pairs_blocked_or_insufficient = 0
    if root.is_dir():
        for pair_dir in root.iterdir():
            if not pair_dir.is_dir():
                continue
            pairs_total += 1
            run = service.find_run_for_pair(pair_dir.name)
            status_path = None
            if run is not None:
                status_path = run / "status.json"
            if status_path is not None and status_path.is_file():
                st = json.loads(status_path.read_text(encoding="utf-8"))
                if st.get("state") == "COMPLETE":
                    pairs_complete += 1
                else:
                    pairs_blocked_or_insufficient += 1
            else:
                pairs_blocked_or_insufficient += 1
    return {
        "total_registration_pairs": pairs_total,
        "complete_pairs": pairs_complete,
        "blocked_or_insufficient_pairs": pairs_blocked_or_insufficient,
        "note": "Registration summary (M6); not a scientific alignment claim.",
    }


class RunRequest(BaseModel):
    registration_configuration_id: str | None = None


@router.get("/{pair_id}/status")
def pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    return service.read_status(pair_id)


@router.post("/{pair_id}/run")
def run_registration(pair_id: str, current: AnalystUser, req: RunRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    rg_cfg_id = req.registration_configuration_id or "RG-M6-001"
    if rg_cfg_id not in VALID_REGISTRATION_CONFIG_IDS:
        raise NotFoundError(f"Unknown registration configuration: {rg_cfg_id}")
    service = _service(settings)
    return guard_run(
        settings, derived_stage="registration", pair_id=pair_id,
        configuration_id=rg_cfg_id, tag="m6_registration",
        fn=lambda: service.run(pair_id, registration_config_id=rg_cfg_id),
    )


@router.post("/{pair_id}/reset")
def reset_pair(pair_id: str, current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    service.reset(pair_id)
    return {
        "reset": True,
        "pair_id": pair_id,
        "status": service.read_status(pair_id),
        "note": "Only derived registration artifacts were removed. M5/M4/M3/M2/raw data untouched.",
    }


@router.get("/{pair_id}/manifest")
def pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.manifest(pair_id)
    if "error" in result:
        raise NotFoundError(f"No registration manifest for pair {pair_id} — run REGISTRATION first.")
    return {"pair_id": pair_id, "manifest": result}


@router.get("/{pair_id}/summary")
def pair_summary(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.summary(pair_id)
    if "error" in result:
        raise NotFoundError(f"No registration summary for pair {pair_id} — run REGISTRATION first.")
    return {"pair_id": pair_id, "summary": result}


@router.get("/{pair_id}/transform")
def pair_transform(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.transform(pair_id)
    if "error" in result:
        raise NotFoundError(f"No registration transform for pair {pair_id}.")
    return {"pair_id": pair_id, "transform": result}


@router.get("/{pair_id}/diagnostics")
def pair_diagnostics(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.diagnostics(pair_id)
    if "error" in result:
        raise NotFoundError(f"No registration diagnostics for pair {pair_id}.")
    return {"pair_id": pair_id, "diagnostics": result}


@router.get("/{pair_id}/validation")
def pair_validation(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.validation(pair_id)
    if "error" in result:
        raise NotFoundError(f"No registration validation for pair {pair_id}.")
    return {"pair_id": pair_id, "validation": result}


@router.get("/{pair_id}/provenance")
def pair_provenance(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.provenance(pair_id)
    if "error" in result:
        raise NotFoundError(f"No registration provenance for pair {pair_id}.")
    return {"pair_id": pair_id, "provenance": result}


@router.get("/{pair_id}/registered-overlay")
def pair_registered_overlay(pair_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    png = run_dir / "visualizations" / "registered_overlay.png"
    if not png.is_file():
        raise NotFoundError(f"No registered overlay visualization for pair {pair_id}.")
    return FileResponse(str(png), media_type="image/png", filename=png.name)


_VISUALIZATION_KINDS = {
    "registered_overlay": "registered warped source crop (normalized preview)",
    "before_after": "source A / source B / registered side-by-side",
    "difference_overlay": "absolute pixel difference of source B vs registered",
    "correspondences": "M5-selected correspondences drawn on the source crop",
    "footprint": "selected-evidence region boxes on source A and source B",
}


@router.get("/{pair_id}/visualizations")
def pair_visualizations(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    viz_dir = run_dir / "visualizations"
    if not viz_dir.is_dir():
        raise NotFoundError(f"No registration visualizations for pair {pair_id}.")
    items = []
    for name in sorted(p.name for p in viz_dir.glob("*.png")):
        p = viz_dir / name
        items.append({
            "name": name,
            "kind": name.rsplit(".", 1)[0],
            "description": _VISUALIZATION_KINDS.get(name.rsplit(".", 1)[0], "registration visualization"),
            "size_bytes": p.stat().st_size if p.is_file() else 0,
            "url": f"/api/registration/{pair_id}/visualizations/{name}",
        })
    return {
        "pair_id": pair_id,
        "visualizations": items,
        "note": "Best-effort inspection aids; not scientific alignment evidence.",
    }


@router.get("/{pair_id}/visualizations/{name}")
def pair_visualization_file(pair_id: str, name: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    _require_pair(settings, pair_id)
    if not name.endswith(".png"):
        raise NotFoundError("Only .png visualization files are served.")
    if name.rsplit(".", 1)[0] not in _VISUALIZATION_KINDS:
        raise NotFoundError(f"Unknown visualization kind: {name}")
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    png = run_dir / "visualizations" / name
    if not png.is_file():
        raise NotFoundError(f"No visualization '{name}' for pair {pair_id}.")
    return FileResponse(str(png), media_type="image/png", filename=name)


@router.get("/{pair_id}/registered-product")
def pair_registered_product(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    registered_dir = run_dir / "registered"
    npy = registered_dir / "registered_image.npy"
    png = registered_dir / "registered_image.png"
    valid = registered_dir / "valid_mask.npy"
    if not npy.is_file():
        raise NotFoundError(f"No registered product for pair {pair_id}.")
    meta = {}
    meta_path = registered_dir / "registered_meta.json"
    if meta_path.is_file():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f) or {}
    return {
        "pair_id": pair_id,
        "product": {
            "array": f"/api/registration/{pair_id}/registered-product/array",
            "valid_mask": f"/api/registration/{pair_id}/registered-product/valid-mask",
            "preview_png": f"/api/registration/{pair_id}/registered-product/preview",
            "meta": meta,
        },
        "note": "Registered output is a warped source crop; diagnostics are measurements, not proof.",
    }


@router.get("/{pair_id}/registered-product/array")
def pair_registered_array(pair_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    npy = run_dir / "registered" / "registered_image.npy"
    if not npy.is_file():
        raise NotFoundError(f"No registered array for pair {pair_id}.")
    return FileResponse(str(npy), media_type="application/octet-stream", filename=npy.name)


@router.get("/{pair_id}/registered-product/valid-mask")
def pair_registered_valid_mask(pair_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    npy = run_dir / "registered" / "valid_mask.npy"
    if not npy.is_file():
        raise NotFoundError(f"No valid mask for pair {pair_id}.")
    return FileResponse(str(npy), media_type="application/octet-stream", filename=npy.name)


@router.get("/{pair_id}/registered-product/preview")
def pair_registered_preview(pair_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No registration run for pair {pair_id}.")
    png = run_dir / "registered" / "registered_image.png"
    if not png.is_file():
        raise NotFoundError(f"No registered preview for pair {pair_id}.")
    return FileResponse(str(png), media_type="image/png", filename=png.name)


@router.get("/{pair_id}/selected-evidence")
def pair_selected_evidence(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.selected_evidence(pair_id)
    if "error" in result:
        raise NotFoundError(f"No M5-selected evidence available for pair {pair_id}: {result.get('detail', result['error'])}")
    return result