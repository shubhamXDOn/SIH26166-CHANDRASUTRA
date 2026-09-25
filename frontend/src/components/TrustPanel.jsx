import { useEffect, useMemo, useState } from "react";

import { Badge, Icon, Modal } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

const TILE_TONES = {
  TRUSTED: "ok",
  REJECTED: "danger",
  INSUFFICIENT: "warn",
  NOT_RUN: "neutral",
  RUNNING: "blue",
  FAILED: "danger",
};

function gateTone(state) {
  if (state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED") return "danger";
  return "neutral";
}

export default function TrustPanel({ pairId, notify }) {
  const { canMutate } = useAuth();
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [tiles, setTiles] = useState(null);
  const [corr, setCorr] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      try {
        const st = await apiGet(`/trust/${pairId}/status`);
        setStatus(st);
      } catch (e) {
        setError(e);
        return;
      }
      let s = null;
      let t = null;
      let c = null;
      if (st.gate_state === "COMPLETE") {
        try {
          s = (await apiGet(`/trust/${pairId}/summary`)).summary;
        } catch {
          /* none */
        }
        try {
          t = (await apiGet(`/trust/${pairId}/tiles`)).tiles;
        } catch {
          /* none */
        }
        try {
          c = (await apiGet(`/trust/${pairId}/trusted-correspondences`)).trusted_correspondences;
        } catch {
          /* none */
        }
      }
      setSummary(s);
      setTiles(t);
      setCorr(c);
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runTrust() {
    setBusy(true);
    setError(null);
    try {
      const st = await apiPost(`/trust/${pairId}/run`, {});
      setStatus(st);
      if (st.gate_state === "BLOCKED") {
        notify({
          title: `TRUST blocked · ${st.block_code ?? "?"}`,
          message: st.reasons?.join(", ") ?? "Blocked honestly at the trust gate.",
          tone: "warn",
        });
      } else if (st.gate_state === "COMPLETE") {
        notify({
          title: `Trust Gate complete · ${pairId}`,
          message: "Independent geometric verification ran. See per-tile trust results below.",
          tone: "ok",
        });
      } else if (st.gate_state === "FAILED") {
        notify({
          title: `Trust Gate failed · ${pairId}`,
          message: "No tile achieved TRUSTED under the active policy.",
          tone: "warn",
        });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "TRUST run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function resetTrust() {
    setBusy(true);
    try {
      const r = await apiPost(`/trust/${pairId}/reset`);
      setStatus(r.status);
      setSummary(null);
      setTiles(null);
      setCorr(null);
      notify({
        title: `${pairId} trust reset`,
        message: "Only derived trust artifacts were removed. M3/M2 products and raw/ are untouched.",
        tone: "ok",
      });
    } catch (e) {
      notify({ title: "Reset failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function openManifest() {
    try {
      const m = (await apiGet(`/trust/${pairId}/manifest`)).manifest;
      setManifest(m);
    } catch (e) {
      notify({ title: "No trust manifest", message: e.message, tone: "danger" });
    }
  }

  return (
    <section className="space-y-4">
      {/* header + controls */}
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="eyebrow">M7 · Geometric Validation Gate</p>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Trust Gate — <span className="font-mono text-teal-300">{pairId}</span>
              </h3>
              <Badge tone={gateTone(status?.gate_state ?? "NOT_STARTED")}>
                {status?.gate_state ?? "NOT_STARTED"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">{status?.trust_configuration_id ?? "TG-M4-001"}</code> ·
              independent geometric verification of M3 candidate sets · deterministic RANSAC with a fixed seed ·
              BLOCKED and REJECTED are first-class outcomes.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run the Trust Gate" : "Analyst or admin required"} onClick={runTrust}>
              <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "Run TRUST"}
            </button>
            <button className="btn-ghost" disabled={busy || !canMutate} title={canMutate ? "Reset pair state" : "Analyst or admin required"} onClick={resetTrust}>
              <Icon.Refresh className="h-4 w-4" /> Reset
            </button>
            <button
              className="btn-ghost"
              disabled={busy || status?.gate_state !== "COMPLETE"}
              onClick={openManifest}
              title="Trust provenance manifest"
            >
              <Icon.Database className="h-4 w-4" /> Manifest
            </button>
          </div>
        </div>
        {error && (
          <p className="mt-3 flex items-center gap-2 text-xs text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> {error.message}
          </p>
        )}
      </div>

      {status?.gate_state === "BLOCKED" && (
        <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-warn">
            <Icon.Info className="h-3.5 w-3.5" /> BLOCKED · {status.block_code}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {status.reasons?.join(", ") ?? "Trust gate stopped honestly — no verifiable candidates to inspect."}
          </p>
        </div>
      )}
      {status?.gate_state === "FAILED" && (
        <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> FAILED · no TRUSTED tile under TG-M4-001
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            Every tile was rejected or insufficient under the active acceptance policy. This is a truthful,
            first-class outcome — no registration follows.
          </p>
        </div>
      )}

      {status?.gate_state === "COMPLETE" && summary && <TrustSummary summary={summary} corr={corr} />}

      {tiles && (
        <TrustTileExplorer tiles={tiles} pairId={pairId} />
      )}

      <div className="card border-warn/30 bg-warn/[0.06] p-4">
        <p className="flex items-start gap-2 text-[11px] leading-relaxed text-warn">
          <Icon.Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            A TRUSTED tile passes the M4 geometric gate (inlier geometry, spatial support, cross-check) under
            the registered configuration — it is <strong>verified spatial evidence for model fitting</strong>, not
            an absolute accuracy claim. M6 registration feeds on the M5-selected evidence produced from
            these trusted correspondences; diagnostics are measurements, never scientific truth.
          </span>
        </p>
      </div>

      <Modal open={!!manifest} onClose={() => setManifest(null)} title={`Trust manifest · ${pairId}`}>
        {manifest && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(manifest, null, 2)}
          </pre>
        )}
      </Modal>
    </section>
  );
}

function TrustSummary({ summary, corr }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ok">{summary.trusted_tiles} trusted tile{summary.trusted_tiles === 1 ? "" : "s"}</Badge>
        <Badge tone="danger">{summary.rejected_tiles} rejected</Badge>
        <Badge tone="warn">{summary.failed_tiles} failed</Badge>
        <Badge tone="blue">{summary.tiles_processed} processed</Badge>
        {corr && <Badge tone="gold">trusted correspondences {corr.x_a_count ?? "—"}</Badge>}
      </div>
      <p className="text-[11px] leading-relaxed text-muted">
        {summary.reason_distribution && (
          <span className="font-mono text-slate-300">{JSON.stringify(summary.reason_distribution)}</span>
        )}
        {" · "}Tiles that pass all geometric checks are the verified evidence source for the future registration
        milestone. Determinism: same Pair + Config IDs produce the same trust set.
      </p>
    </div>
  );
}

function TrustTileExplorer({ tiles, pairId }) {
  return (
    <div className="space-y-3">
      <p className="text-[11px] font-bold uppercase tracking-wider text-muted">Per-tile trust decisions</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {tiles.map((t) => {
          const tone = TILE_TONES[t.trust_state] ?? "neutral";
          const model = t.model ?? {};
          const spatial = t.spatial ?? {};
          return (
            <div
              key={t.tile_id}
              className={`rounded-lg border p-3 ${
                t.trust_state === "TRUSTED"
                  ? "border-ok/30 bg-ok/[0.05]"
                  : t.trust_state === "REJECTED"
                    ? "border-danger/25 bg-danger/[0.04]"
                    : "border-white/[0.07] bg-space-900/40"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="truncate font-mono text-[11px] font-semibold text-slate-200">{t.tile_id}</p>
                <Badge tone={tone}>{t.trust_state}</Badge>
              </div>
              {t.trust_state === "TRUSTED" && (
                <div className="mt-2 space-y-1 text-[10.5px]">
                  <p className="text-muted">
                    inliers <span className="font-mono text-slate-300">{model.inlier_count}</span> · ratio{" "}
                    <span className="font-mono text-slate-300">{model.inlier_ratio}</span> · {model.type}
                  </p>
                  <p className="text-muted">
                    residual mean <span className="font-mono text-slate-300">{model.residual_stats?.mean}</span> px
                  </p>
                  <p className="text-muted">
                    spatial <span className="font-mono text-slate-300">{spatial.grid_cells_occupied}/{spatial.total_cells}</span>{" "}
                    cells · spread {spatial.coordinate_spread_x?.toFixed?.(1) ?? spatial.coordinate_spread_x}
                  </p>
                  {t.cross_check && (
                    <p className="text-muted">
                      cross-check max <span className="font-mono text-slate-300">{t.cross_check.max_symmetric_transfer_px}</span> px
                    </p>
                  )}
                </div>
              )}
              {t.trust_state !== "TRUSTED" && (
                <div className="mt-2 space-y-1">
                  <p className="text-[10.5px] text-muted">
                    {t.block_code ? `${t.block_code} · ` : ""}
                    {(t.reasons ?? []).join(", ") || "no evidence"}
                  </p>
                  {t.error && <p className="text-[10.5px] text-danger">{t.error}</p>}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {tiles.length === 0 && <p className="text-xs text-muted">No tiles evaluated.</p>}
      <p className="sr-only">Trust decisions for pair {pairId}.</p>
    </div>
  );
}