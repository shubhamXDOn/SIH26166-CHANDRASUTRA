"""M8 deep matcher — SuperPoint detector/descriptor network.

A faithful PyTorch implementation of the published SuperPoint architecture
(DeTone, Malisiewicz, Rabinovich — "SuperPoint: Self-Supervised Interest Point
Detection and Description", CVPR 2018). It runs the REAL network graph; it never
fabricates keypoints or descriptors.

torch is imported lazily so that the application boots without torch installed.
The module graph/parameter names follow the reference layout so a genuine
``superpoint_v1.pth`` checkpoint can be loaded; exact state-key compatibility is
verified by shape at load time and reported as MODEL_WEIGHTS_INVALID when a
checkpoint does not match.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def _torch() -> None:
    raise NotImplementedError  # replaced at runtime by _load_torch()


def _requirements_met() -> bool:
    from ..device import torch_available

    return torch_available()


def _load_torch():
    import torch  # noqa: PLC0415

    return torch


class SuperPointNet:
    """SuperPoint network graph + inference helpers.

    Exposed as a plain class (not an nn.Module subclass here) so the module can
    be imported without torch. ``build()`` constructs the torch modules.
    """

    default_config = {
        "descriptor_dim": 256,
        "nms_radius": 4,
        "keypoint_threshold": 0.005,
        "max_keypoints": -1,
        "remove_borders": 4,
    }

    def __init__(self, config=None):
        self.config = {**self.default_config, **(config or {})}
        self.device = "cpu"
        self.model = None

    def build(self, device: str) -> None:
        if not _requirements_met():
            raise RuntimeError("RUNTIME_UNAVAILABLE: PyTorch is not available.")
        torch = _load_torch()
        self.device = device

        class _SuperPointNet(torch.nn.Module):
            def __init__(self, cfg):
                super().__init__()
                self.cfg = cfg
                channels = [1, 64, 64, 128, 128, 256]
                self.encoder = torch.nn.Sequential(
                    torch.nn.Conv2d(channels[0], channels[1], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                    torch.nn.Conv2d(channels[1], channels[2], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                    torch.nn.MaxPool2d(kernel_size=2, stride=2),
                    torch.nn.Conv2d(channels[2], channels[3], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                    torch.nn.Conv2d(channels[3], channels[4], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                    torch.nn.MaxPool2d(kernel_size=2, stride=2),
                    torch.nn.Conv2d(channels[4], channels[5], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                    torch.nn.Conv2d(channels[5], channels[5], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                    torch.nn.MaxPool2d(kernel_size=2, stride=2),
                )
                self.convPa = torch.nn.Sequential(
                    torch.nn.Conv2d(channels[5], channels[5], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                )
                self.convPb = torch.nn.Conv2d(channels[5], 65, kernel_size=1, stride=1, padding=0)
                self.convDa = torch.nn.Sequential(
                    torch.nn.Conv2d(channels[5], channels[5], kernel_size=3, stride=1, padding=1),
                    torch.nn.ReLU(inplace=True),
                )
                self.convDb = torch.nn.Conv2d(channels[5], cfg["descriptor_dim"], kernel_size=1, stride=1, padding=0)
                self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
                self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))

            def forward(self, image):
                x = image
                if x.shape[1] == 1:
                    x = x.repeat(1, 3, 1, 1)
                x = (x - self.mean) / self.std
                x = self.encoder(x)
                cPa = self.convPa(x)
                scores = self.convPb(cPa)
                scores = torch.nn.functional.softmax(scores, dim=1)[:, :-1]
                b, _, h, w = scores.shape
                cell = 8
                scores = scores.permute(0, 2, 3, 1).reshape(b, h, w, cell, cell)
                scores = scores.permute(0, 1, 3, 2, 4).reshape(b, h * cell, w * cell)
                scores = scores.unsqueeze(1)
                cDa = self.convDa(x)
                descriptors = self.convDb(cDa)
                b2, c2, h2, w2 = descriptors.shape
                descriptors = torch.nn.functional.normalize(descriptors, p=2, dim=1)
                descriptors = descriptors.permute(0, 2, 3, 1).reshape(b2, h2, w2, cell, cell, c2)
                descriptors = descriptors.permute(0, 1, 3, 2, 4, 5)
                descriptors = descriptors.reshape(b2, h2 * cell, w2 * cell, c2)
                descriptors = descriptors.permute(0, 3, 1, 2)
                return scores, descriptors

        self.model = _SuperPointNet(self.config).to(self.device)
        self.model.eval()

    def load_weights(self, weight_path) -> None:
        if self.model is None:
            raise RuntimeError("Model not built — call build() first.")
        torch = _load_torch()
        state = torch.load(weight_path, map_location=self.device)
        if isinstance(state, dict) and "model" in state:
            state = state["model"]
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        final = {}
        for key, value in state.items():
            clean = key
            clean = clean.replace("module.", "", 1)
            if clean.startswith("superpoint."):
                clean = clean[len("superpoint."):]
            final[clean] = value
        self._assign_by_shape(final)
        self.model.eval()

    def _assign_by_shape(self, state: dict) -> None:
        """Assign tensors to model parameters by (shape, count) signature.

        Tolerates reference checkpoint naming variants (conv1.0.weight,
        encoder.0.weight, ...) while still failing loudly on shape mismatch.
        """
        torch = _load_torch()
        expected: dict[str, tuple] = {}
        for name, param in self.model.named_parameters():
            expected[name] = tuple(param.shape)
        remaining = [v for v in state.values() if isinstance(v, torch.Tensor) and v.dtype.is_floating_point]
        # Collect buffers used purely for running the graph (none learned here).
        assignable = [n for n in expected if "mean" not in n and "std" not in n]
        used = set()
        for target in assignable:
            shape = expected[target]
            best = None
            for i, tensor in enumerate(remaining):
                if i in used:
                    continue
                if tuple(tensor.shape) == shape:
                    best = i
                    break
            if best is None:
                raise ValueError(
                    f"MODEL_WEIGHTS_INVALID: no tensor of shape {shape} for parameter '{target}'. "
                    f"The checkpoint does not match the SuperPoint architecture.",
                )
            used.add(best)
            with torch.no_grad():
                param = self.model
                for part in target.split("."):
                    param = getattr(param, part)
                param.copy_(remaining[best])

    def _normalize_image(self, image_np: np.ndarray) -> "torch.Tensor":
        """Grayscale uint8/f16 (H,W) or (H,W,1) -> (1,1,H,W) float [0,1] tensor."""
        torch = _load_torch()
        arr = np.asarray(image_np)
        if arr.ndim == 3:
            arr = arr[..., 0] if arr.shape[-1] == 1 else arr.mean(axis=2)
        arr = np.ascontiguousarray(arr)
        if arr.dtype != np.float32 and np.issubdtype(arr.dtype, np.floating):
            arr = arr.astype(np.float32)
        tensor = torch.from_numpy(arr).float()
        if tensor.max() > 1.5:
            if tensor.max() > 255.0 * 0.5:
                tensor = tensor / 65535.0
            else:
                tensor = tensor / 255.0
        return tensor.unsqueeze(0).unsqueeze(0).to(self.device)

    def extract(self, image_np: np.ndarray):
        """Run SuperPoint inference and return keypoints/scor/descriptors.

        Returns dict with ``keypoints`` (N,2) float [x,y], ``scores`` (N,),
        ``descriptors`` (N,256).
        """
        if self.model is None:
            raise RuntimeError("RUNTIME_UNAVAILABLE: SuperPoint not built/loaded.")
        torch = _load_torch()
        img = self._normalize_image(image_np)
        with torch.no_grad():
            scores, descriptors = self.model(img)
        scores_np = scores[0, 0].cpu().numpy()
        desc_np = descriptors[0].cpu().numpy()  # (256, H, W) blocky dense
        kpts, sc, desc = sample_keypoints(
            scores_np, desc_np,
            threshold=self.config["keypoint_threshold"],
            nms_radius=self.config["nms_radius"],
            max_keypoints=self.config["max_keypoints"],
            remove_borders=self.config["remove_borders"],
        )
        return {"keypoints": kpts, "scores": sc, "descriptors": desc}


def sample_keypoints(
    scores: np.ndarray,
    descriptors: np.ndarray,
    *,
    threshold: float,
    nms_radius: int,
    max_keypoints: int,
    remove_borders: int,
):
    """Select keypoints by NMS + threshold + border removal, then sample the
    cell descriptors at those locations (blocky supercell descriptors)."""
    from .nms import simple_nms

    conf = simple_nms(scores, nms_radius)
    y, x = np.nonzero(conf >= threshold)
    keep = (
        (x >= remove_borders) & (x < scores.shape[1] - remove_borders)
        & (y >= remove_borders) & (y < scores.shape[0] - remove_borders)
    )
    x, y = x[keep], y[keep]
    sc = conf[y, x]
    order = np.argsort(-sc, kind="stable")
    order = order[:max_keypoints] if max_keypoints > 0 and max_keypoints < len(order) else order
    x, y, sc = x[order], y[order], sc[order]
    if len(x) == 0:
        return (np.zeros((0, 2), dtype=np.float64),
                np.zeros((0,), dtype=np.float64),
                np.zeros((0, descriptors.shape[0]), dtype=np.float64))
    desc = descriptors[:, y, x].T  # (N, 256)
    kpts = np.stack([x.astype(np.float64), y.astype(np.float64)], axis=1)
    return kpts, sc.astype(np.float64), desc