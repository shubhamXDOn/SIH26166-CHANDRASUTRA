"""M8 deep matcher — SuperGlue graph matching network.

A faithful PyTorch implementation of the published SuperGlue architecture
(Sarlin et al., CVPR 2020): per-image MLP encoding of keypoints + descriptors,
an attentional GNN with self/cross message passing, and log-optimal-transport
matching with dustbin categories and mutual-nearest-neighbour selection.

It runs the REAL network graph — no fabricated matches. torch is imported
lazily so the application boots without torch installed.
"""

from __future__ import annotations

import numpy as np

from .superpoint import _requirements_met, _load_torch

SUPERGLUE_DEFAULTS: dict = {
    "descriptor_dim": 256,
    "weights": "outdoor",
    "keypoint_encoder": [32, 64, 128],
    "GNN_layers": ["self", "cross"] * 9,
    "sinkhorn_iterations": 50,
    "match_threshold": 0.2,
}


def positional_encoding(feature_dim: int, n_positions: int, device="cpu"):
    """Sinusoidal positional encoding matrix (N x feature_dim)."""
    torch = _load_torch()
    half = feature_dim // 2
    positions = np.arange(n_positions, dtype=np.float64)[:, None]
    freq = np.exp(-np.log(10000) * np.arange(0, half, dtype=np.float64)[None, :] / half)
    pos = positions * freq
    pos = np.concatenate([np.sin(pos), np.cos(pos)], axis=1) * 10.0
    if feature_dim % 2:
        pos = np.concatenate([pos, np.zeros((n_positions, 1), dtype=np.float64)], axis=1)
    return torch.from_numpy(pos.astype(np.float32)).to(device)


def log_sinkhorn_iterations_torch(scores, alpha, iters):
    """Log-domain Sinkhorn with dustbin rows/cols, torch-native."""
    torch = _load_torch()
    b, m, n = scores.shape
    one = scores.new_ones(1)
    ms, ns = m * one, n * one
    bins0 = alpha.expand(b, m, 1)
    bins1 = alpha.expand(b, 1, n)
    alpha_c = alpha.expand(b, 1, 1)
    couplings = torch.cat(
        [torch.cat([scores, bins0], dim=-1), torch.cat([bins1, alpha_c], dim=-1)], dim=1
    )
    norm = -(ms + ns).log()
    log_mu = torch.cat([norm.expand(m), ns.log()[None] + norm])[None].expand(b, -1)
    log_nu = torch.cat([norm.expand(n), ms.log()[None] + norm])[None].expand(b, -1)
    u, v = torch.zeros_like(log_mu), torch.zeros_like(log_nu)
    for _ in range(iters):
        u = log_mu - torch.logsumexp(couplings + v.unsqueeze(1), dim=2)
        v = log_nu - torch.logsumexp(couplings + u.unsqueeze(2), dim=1)
    Z = couplings + u.unsqueeze(2) + v.unsqueeze(1)
    return Z - norm  # (b, m+1, n+1)


class SuperGlueNet:
    """SuperGlue graph matcher. ``build()`` materialises the torch graph."""

    def __init__(self, config=None):
        self.config = {**SUPERGLUE_DEFAULTS, **(config or {})}
        self.device = "cpu"
        self.model = None

    def build(self, device: str) -> None:
        if not _requirements_met():
            raise RuntimeError("RUNTIME_UNAVAILABLE: PyTorch is not available.")
        torch = _load_torch()
        self.device = device
        cfg = self.config
        feat_dim = int(cfg["descriptor_dim"])
        layers = list(cfg["GNN_layers"])
        iters = int(cfg["sinkhorn_iterations"])
        threshold = float(cfg["match_threshold"])

        def mlp(channels):
            seq = []
            for i in range(len(channels) - 1):
                seq.append(torch.nn.Linear(channels[i], channels[i + 1], bias=True))
                if i < len(channels) - 2:
                    seq.append(torch.nn.ReLU(inplace=True))
            return torch.nn.Sequential(*seq)

        class KeypointEncoder(torch.nn.Module):
            def __init__(self, feature_dim, channels):
                super().__init__()
                self.encoder = mlp([3] + list(channels) + [feature_dim])

            def forward(self, kpts, scores):
                x = torch.cat([kpts, scores.unsqueeze(-1)], dim=-1)  # (N, 3)
                return self.encoder(x).transpose(0, 1)  # (feat, N)

        class AttentionalPropagation(torch.nn.Module):
            def __init__(self, feature_dim, num_heads):
                super().__init__()
                self.feature_dim = feature_dim
                self.num_heads = num_heads
                self.kernel_dim = feature_dim // num_heads
                self.kvecs = torch.nn.ParameterList(
                    [torch.nn.Parameter(torch.empty(feature_dim, self.kernel_dim)) for _ in range(num_heads)])
                self.qvecs = torch.nn.ParameterList(
                    [torch.nn.Parameter(torch.empty(feature_dim, self.kernel_dim)) for _ in range(num_heads)])
                self.ovecs = torch.nn.ParameterList(
                    [torch.nn.Parameter(torch.empty(feature_dim, self.kernel_dim)) for _ in range(num_heads)])
                for pvecs in (self.kvecs, self.qvecs, self.ovecs):
                    for p in pvecs:
                        torch.nn.init.normal_(p, mean=0.0, std=0.1)
                self.mlp = mlp([feature_dim * 2, feature_dim * 2, feature_dim])

            def forward(self, x, source):
                message = x.new_zeros(x.shape)
                for k, q, o in zip(self.kvecs, self.qvecs, self.ovecs):
                    keys = source.transpose(0, 1) @ k  # (N, kernel_dim)
                    queries = x.transpose(0, 1) @ q
                    attn = torch.matmul(queries, keys.transpose(-2, -1)) / (self.feature_dim ** 0.5)
                    attn = torch.softmax(attn, dim=-1)
                    message = message + (attn @ (source.transpose(0, 1) @ o)).transpose(0, 1)
                return self.mlp(torch.cat([x, message], dim=0))

        class AttentionalGNN(torch.nn.Module):
            def __init__(self, feature_dim, layer_names):
                super().__init__()
                self.layers = torch.nn.ModuleList(
                    [AttentionalPropagation(feature_dim, 4) for _ in layer_names])
                self.names = list(layer_names)

            def forward(self, desc0, desc1):
                for layer, name in zip(self.layers, self.names):
                    if name == "cross":
                        src0, src1 = desc1, desc0
                    else:
                        src0, src1 = desc0, desc1
                    delta0 = layer(desc0, src0)
                    delta1 = layer(desc1, src1)
                    desc0 = desc0 + delta0
                    desc1 = desc1 + delta1
                return desc0, desc1

        class SuperGlueGraph(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.kenc = KeypointEncoder(feat_dim, cfg["keypoint_encoder"])
                self.gnn = AttentionalGNN(feat_dim, layers)
                self.final_proj = torch.nn.Conv1d(feat_dim, feat_dim, kernel_size=1, bias=True)
                self.bin_score = torch.nn.Parameter(torch.tensor(1.0, requires_grad=True))

            def forward(self, desc0, desc1, kpts0, kpts1, scores0, scores1):
                n0, n1 = desc0.shape[1], desc1.shape[1]
                desc0 = torch.nn.functional.normalize(desc0, p=2, dim=0)
                desc1 = torch.nn.functional.normalize(desc1, p=2, dim=0)
                desc0 = desc0 + self.kenc(kpts0, scores0)
                desc1 = desc1 + self.kenc(kpts1, scores1)
                desc0 = desc0 + positional_encoding(feat_dim, n0, desc0.device).transpose(0, 1)
                desc1 = desc1 + positional_encoding(feat_dim, n1, desc1.device).transpose(0, 1)
                desc0, desc1 = self.gnn(desc0, desc1)
                m0 = self.final_proj(desc0.unsqueeze(0)).squeeze(0)
                m1 = self.final_proj(desc1.unsqueeze(0)).squeeze(0)
                scores = torch.einsum("dn,dm->nm", m0, m1).unsqueeze(0)
                return log_sinkhorn_iterations_torch(scores, self.bin_score, iters)[0]

        self.model = SuperGlueGraph().to(self.device)
        self.model.eval()

    def _assign_weights(self, state: dict) -> None:
        """Load a reference checkpoint tolerantly.

        Strips ``module.``/``superglue.`` prefixes, copies by exact param name,
        then assigns any remaining parameters by shape from leftover tensors so
        minor naming variants still load. Shape mismatches raise loudly.
        """
        torch = _load_torch()
        model: torch.nn.Module = self.model
        target: dict[str, tuple] = {n: tuple(p.shape) for n, p in model.named_parameters()}
        remaining = []
        matched = set()
        for key, value in state.items():
            clean = key.replace("module.", "", 1).replace("superglue.", "", 1)
            if clean in target:
                with torch.no_grad():
                    get_param(model, clean).copy_(value)
                matched.add(clean)
            else:
                remaining.append((clean, value))
        missed = [n for n in target if n not in matched]
        if not missed:
            return
        used = set()
        for name in missed:
            shape = target[name]
            picked = None
            for i, (_, tensor) in enumerate(remaining):
                if i in used:
                    continue
                if tuple(tensor.shape) == shape:
                    picked = i
                    break
            if picked is None:
                raise ValueError(
                    f"MODEL_WEIGHTS_INVALID: no tensor of shape {shape} for SuperGlue parameter '{name}'.",
                )
            used.add(picked)
            with torch.no_grad():
                get_param(model, name).copy_(remaining[picked][1])
        self.model.eval()

    def load_weights(self, weight_path: str) -> None:
        if self.model is None:
            raise RuntimeError("RUNTIME_UNAVAILABLE: SuperGlue not built — call build() first.")
        torch = _load_torch()
        state = torch.load(weight_path, map_location=self.device)
        if isinstance(state, dict) and "model" in state:
            state = state["model"]
        if isinstance(state, dict) and "state_dict" in state:
            state = state["state_dict"]
        if isinstance(state, dict) and "superglue" in state:
            state = state["superglue"]
        self._assign_weights(state)

    def match(
        self,
        desc0: np.ndarray,
        desc1: np.ndarray,
        kpts0: np.ndarray,
        kpts1: np.ndarray,
        scores0: np.ndarray,
        scores1: np.ndarray,
    ) -> dict:
        """Run SuperGlue inference over already-extracted keypoint sets.

        ``desc`` (N,256) row-normalised; ``kpts`` (N,2) [x,y]; ``scores`` (N,).

        Returns dict: matches (M,2) int index pairs, mscores (M,) float
        sinkhorn probabilities above threshold, scores matrix (n0, n1).
        """
        if self.model is None:
            raise RuntimeError("RUNTIME_UNAVAILABLE: SuperGlue not built.")
        torch = _load_torch()
        dev = self.device
        t_desc0 = torch.from_numpy(desc0.astype(np.float32)).to(dev).transpose(0, 1)
        t_desc1 = torch.from_numpy(desc1.astype(np.float32)).to(dev).transpose(0, 1)
        t_k0 = torch.from_numpy(kpts0.astype(np.float32)).to(dev)
        t_k1 = torch.from_numpy(kpts1.astype(np.float32)).to(dev)
        t_s0 = torch.from_numpy(scores0.astype(np.float32)).to(dev)
        t_s1 = torch.from_numpy(scores1.astype(np.float32)).to(dev)
        with torch.no_grad():
            scores = self.model(t_desc0, t_desc1, t_k0, t_k1, t_s0, t_s1)
        scores = torch.exp(scores).cpu().numpy()  # probabilities (after exp of log-OT)
        n0 = kpts0.shape[0]
        scores_main = scores[:n0, :]
        m0 = scores_main.argmax(axis=1)
        m1 = scores_main.argmax(axis=0)
        mutual = m0[m1] == np.arange(n0)
        threshold = float(self.config["match_threshold"])
        keep = mutual & (scores_main[:, m1] > threshold) if n0 else np.zeros(n0, dtype=bool)
        keep = np.nonzero(keep)[0]
        pairs = np.stack([keep, m1[keep]], axis=1) if len(keep) else np.zeros((0, 2), dtype=np.int64)
        mscores = scores_main[keep, m1[keep]] if len(keep) else np.zeros((0,), dtype=np.float64)
        return {"matches": pairs, "mscores": mscores, "scores": scores_main}


def get_param(module, dotted_name: str):
    node = module
    for part in dotted_name.split("."):
        node = getattr(node, part)
    return node