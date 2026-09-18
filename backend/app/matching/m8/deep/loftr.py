"""M8 LoFTR deep matcher adapter.

LoFTR (detector-free local feature matching) requires the ``kornia`` runtime and
a LoFTR feature-matching pipeline. kornia is NOT shipped with this project, so
the adapter truthfully reports RUNTIME_UNAVAILABLE in production builds. No
weights are downloaded and no output is fabricated when unavailable.
"""

from __future__ import annotations

from typing import Any

from ..base import BaseMatcherAdapter, M8AdapterOutput
from ..device import kornia_available


class LoFTRAdapter(BaseMatcherAdapter):
    matcher_id = "loftr"
    family = "deep"
    display_name = "LoFTR (detector-free transformer matcher — optional)"
    requires_weights = True
    supports_cpu = True
    supports_gpu = True
    runtime_name = "kornia"

    def __init__(self, model_dir: str = "", device: str = "auto"):
        self.model_dir = model_dir
        self.requested_device = device
        self._kornia_ok = False

    def runtime_available(self) -> bool:
        self._kornia_ok = kornia_available()
        return self._kornia_ok

    def weights_available(self) -> bool:
        # LoFTR's pretrained weights are fetched by kornia on first use; this
        # repository explicitly does not vend or download them.
        return False

    def reason_if_unavailable(self) -> str:
        if not self.runtime_available():
            return "RUNTIME_UNAVAILABLE"
        return "MODEL_WEIGHTS_NOT_CONFIGURED"

    def is_available(self) -> bool:
        return False

    def prepare(self) -> None:
        raise RuntimeError(self.reason_if_unavailable())

    def match(self, tile_pair: dict[str, Any]) -> M8AdapterOutput:
        return M8AdapterOutput(
            matcher_id=self.matcher_id,
            matcher_family=self.family,
            matcher_version=self.matcher_version,
            ok=False,
            failure_code=self.reason_if_unavailable(),
            failure_detail="LoFTR requires the kornia runtime and model weights, which are not available in this build.",
        )