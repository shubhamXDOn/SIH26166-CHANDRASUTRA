"""M4 trust gate API (/api/trust).

Independent geometric verification + trust gate decisions. Blocked and
rejected are first-class truthful outcomes. Nothing here claims scientific
trust until real data + verified configuration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import Settings, m4_config
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..trust.config import TrustConfig
from ..trust.service import TrustService
from .deps import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/trust", tags=["trust"])

VALID_TRUST_CONFIG_IDS = {"TG-M4-001"}


def _service(settings: Settings) -> TrustService:
    return TrustService(settings.data_root_path, m4_config())


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


@router.get("/configurations")
def list_configurations() -> dict:
    cfg = m4_config()
    return {
        "configurations": [
            {
                "trust_configuration_id": cfg.get("trust_configuration_id", "TG-M4-001"),
                "trust_configuration_version": cfg.get("trust_configuration_version", 1),
                "name": cfg.get("name", "Independent Geometric Verification & Trust Gate"),
                "defaults": cfg.get("defaults", {}),
            },
        ],
        "default_trust_configuration_id": "TG-M4-001",
        "valid_trust_configuration_ids": sorted(VALID_TRUST_CONFIG_IDS),
        "note": "Engineering defaults only; no scientifically tuned thresholds exist yet.",
    }


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    root = service._trust_root()
    pairs_trusted = 0
    pairs_blocked = 0
    pairs_total = 0
    if root.is_dir():
        for pair_dir in root.iterdir():
            if not pair_dir.is_dir():
                continue
            pairs_total += 1
            run = service.find_run_for_pair(pair_dir.name)
            if run is None:
                pairs_blocked += 1
                continue
            status_path = run / "trust_status.json"
            if status_path.is_file():
                import json
                with open(status_path, encoding="utf-8") as f:
                    st = json.load(f)
                gate = st.get("gate_state", "")
                if gate == "COMPLETE":
                    pairs_trusted += 1
                else:
                    pairs_blocked += 1
            else:
                pairs_blocked += 1
    return {
        "total_trust_pairs": pairs_total,
        "trusted_pairs": pairs_trusted,
        "blocked_pairs": pairs_blocked,
        "note": "Independent verification summary (M4); not a scientific trust claim.",
    }


@router.get("/{pair_id}/status")
def pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    return service.read_status(pair_id)


class RunRequest:
    pass

from pydantic import BaseModel

class RunRequest(BaseModel):
    trust_configuration_id: str | None = None


@router.post("/{pair_id}/run")
def run_trust(pair_id: str, req: RunRequest, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    trust_cfg_id = req.trust_configuration_id or "TG-M4-001"
    if trust_cfg_id not in VALID_TRUST_CONFIG_IDS:
        raise NotFoundError(f"Unknown trust configuration: {trust_cfg_id}")
    service = _service(settings)
    return service.run(pair_id, trust_config_id=trust_cfg_id)


@router.post("/{pair_id}/reset")
def reset_pair(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    service.reset(pair_id)
    return {
        "reset": True,
        "pair_id": pair_id,
        "status": service.read_status(pair_id),
        "note": "Only derived trust artifacts were removed. M3/M2/raw data untouched.",
    }


@router.get("/{pair_id}/manifest")
def pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.manifest(pair_id)
    if "error" in result:
        raise NotFoundError(f"No trust manifest for pair {pair_id} — run TRUST first.")
    return {"pair_id": pair_id, "manifest": result}


@router.get("/{pair_id}/summary")
def pair_summary(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.summary(pair_id)
    if "error" in result:
        raise NotFoundError(f"No trust summary for pair {pair_id} — run TRUST first.")
    return {"pair_id": pair_id, "summary": result}


@router.get("/{pair_id}/tiles")
def pair_tiles(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    run_dir = service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise NotFoundError(f"No trust run for pair {pair_id} — run TRUST first.")
    tile_trust_path = run_dir / "tile_trust.json"
    if not tile_trust_path.is_file():
        raise NotFoundError(f"No tile trust data for pair {pair_id}.")
    import json
    with open(tile_trust_path, encoding="utf-8") as f:
        data = json.load(f)
    return {"pair_id": pair_id, "tiles": data.get("tiles", [])}


@router.get("/{pair_id}/tiles/{tile_id}")
def pair_tile(pair_id: str, tile_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.tile_trust(pair_id, tile_id)
    if "error" in result:
        raise NotFoundError(f"No trust data for tile {tile_id} of pair {pair_id}.")
    return {"pair_id": pair_id, "tile": result}


@router.get("/{pair_id}/trusted-correspondences")
def pair_trusted_correspondences(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.trusted_correspondences(pair_id)
    if "error" in result:
        raise NotFoundError(f"No trusted correspondences for pair {pair_id}.")
    return {"pair_id": pair_id, "trusted_correspondences": result}
