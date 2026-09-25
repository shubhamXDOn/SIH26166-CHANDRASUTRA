"""M9 REGISTRATION / IMAGE ALIGNMENT API.

Endpoints mounted by ``api/router.py`` (namespaced under ``/registration-m9``;
the legacy M6 router owns ``/api/registration``):

    GET  /api/pairs/{pair_id}/registration-m9/status   (read)
    GET  /api/pairs/{pair_id}/registration-m9/runs     (read)
    POST /api/pairs/{pair_id}/registration-m9/run      (writes one m9 artifact; analyst)
    GET  /api/registration-m9/runs/{run_id}            (read)
    GET  /api/registration-m9/runs/{run_id}/visualization
    GET  /api/registration-m9/runs/{run_id}/visualizations/{name}
    GET  /api/registration-m9/runs/{run_id}/registered
    GET  /api/registration-m9/runs/{run_id}/valid-mask

M9 consumes exactly ONE usable M8 spatial-selection artifact (SELECTED /
SELECTED_WITH_WARNINGS), estimates and independently validates a declared
geometric transform, records residual diagnostics in px of the effective
matcher plane and produces a derived aligned/warped output. It never rewrites
the M7 verdict or the M8 status and never emits ``confidence`` vocabulary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth.dependencies import AnalystUser, current_user_dep
from ..config import Settings
from ..errors import NotFoundError
from ..pairs import PairRegistry
from ..run_guard import guard_run
from .deps import get_settings

pair_router = APIRouter(prefix="/pairs", tags=["registration-m9"],
                        dependencies=[Depends(current_user_dep)])
reg_router = APIRouter(prefix="/registration-m9", tags=["registration-m9"],
                       dependencies=[Depends(current_user_dep)])

_VISUALIZATIONS = {
    "visualization_before_after.png": "before / after panels",
    "visualization_checkerboard.png": "checkerboard B vs registered",
    "visualization_difference.png": "absolute difference map",
    "visualization_overlay.png": "red-green overlay",
    "visualization_residual_vectors.png": "target <- transformed-source residual vectors",
}


class RegistrationM9RunRequest(BaseModel):
    m8_run_id: str | None = None
    model: str = "auto"


def _service(settings: Settings):
    from ..registration_m9.service import RegistrationM9Service

    return RegistrationM9Service(settings)


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


def _resolve_run(settings: Settings, run_id: str) -> dict:
    payload = _service(settings).read(run_id)
    if payload is None:
        raise NotFoundError(f"No M9 registration run with id {run_id}.")
    return payload


# ---------------------------------------------------------------------------
# pair-scoped registration
# ---------------------------------------------------------------------------

@pair_router.get("/{pair_id}/registration-m9/status")
def registration_m9_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _service(settings).status(pair_id)


@pair_router.get("/{pair_id}/registration-m9/runs")
def registration_m9_runs(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return {"pair_id": pair_id, "runs": _service(settings).list_runs(pair_id)}


@pair_router.post("/{pair_id}/registration-m9/run")
def registration_m9_run(pair_id: str, req: RegistrationM9RunRequest,
                        current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    return guard_run(
        settings, derived_stage="registration-m9", pair_id=pair_id,
        configuration_id=service.config.configuration_id,
        tag="m9_registration",
        fn=lambda: service.run(pair_id, m8_run_id=req.m8_run_id, model=req.model),
    )


# ---------------------------------------------------------------------------
# run read surface
# ---------------------------------------------------------------------------

@reg_router.get("/runs/{run_id}")
def registration_m9_run_detail(run_id: str, settings: Settings = Depends(get_settings)) -> dict:
    return _resolve_run(settings, run_id)


@reg_router.get("/runs/{run_id}/visualization")
def registration_m9_run_visualization(run_id: str, settings: Settings = Depends(get_settings)) -> dict:
    payload = _resolve_run(settings, run_id)
    warp = payload.get("warp") or {}
    items = []
    if warp.get("preview_rel"):
        items.append({
            "name": "registered_preview.png",
            "kind": "registered preview (source warped into target-B effective frame)",
            "url": f"/api/registration-m9/runs/{run_id}/preview",
        })
    for name, description in _VISUALIZATIONS.items():
        items.append({
            "name": name,
            "kind": description,
            "url": f"/api/registration-m9/runs/{run_id}/visualizations/{name}",
        })
    return {
        "run_id": run_id,
        "warp_available": bool(warp.get("available")),
        "visualizations": items,
        "note": "Diagnostic visualization of a derived geometric registration; no physical accuracy claim.",
    }


@reg_router.get("/runs/{run_id}/preview")
def registration_m9_run_preview(run_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    payload = _resolve_run(settings, run_id)
    warp = payload.get("warp") or {}
    rel = warp.get("preview_rel")
    if not rel:
        raise NotFoundError(f"Run {run_id} has no registered preview (warp not produced).")
    path = settings.data_root_path / rel
    if not path.is_file():
        raise NotFoundError(f"Run {run_id} registered preview file is missing.")
    return FileResponse(str(path), media_type="image/png", filename="registered_preview.png")


@reg_router.get("/runs/{run_id}/visualizations/{name}")
def registration_m9_run_visualization_file(
    run_id: str, name: str, settings: Settings = Depends(get_settings),
) -> FileResponse:
    if name not in _VISUALIZATIONS:
        raise NotFoundError("Unknown M9 visualization kind.")
    payload = _resolve_run(settings, run_id)
    warp = payload.get("warp") or {}
    rel = warp.get("artifact_ref")
    if not rel:
        raise NotFoundError(f"Run {run_id} has no warp artifacts.")
    path = settings.data_root_path / rel / name
    if not path.is_file():
        raise NotFoundError(f"Run {run_id} {name} is not available.")
    return FileResponse(str(path), media_type="image/png", filename=name)


@reg_router.get("/runs/{run_id}/registered")
def registration_m9_run_registered(run_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    payload = _resolve_run(settings, run_id)
    rel = (payload.get("warp") or {}).get("registered_image_rel")
    if not rel:
        raise NotFoundError(f"Run {run_id} has no registered image.")
    path = settings.data_root_path / rel
    if not path.is_file():
        raise NotFoundError(f"Run {run_id} registered image file is missing.")
    return FileResponse(str(path), media_type="application/octet-stream",
                        filename="registered_image.npy")


@reg_router.get("/runs/{run_id}/valid-mask")
def registration_m9_run_valid_mask(run_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    payload = _resolve_run(settings, run_id)
    rel = (payload.get("warp") or {}).get("valid_mask_rel")
    if not rel:
        raise NotFoundError(f"Run {run_id} has no valid mask.")
    path = settings.data_root_path / rel
    if not path.is_file():
        raise NotFoundError(f"Run {run_id} valid mask file is missing.")
    return FileResponse(str(path), media_type="application/octet-stream",
                        filename="valid_mask.npy")