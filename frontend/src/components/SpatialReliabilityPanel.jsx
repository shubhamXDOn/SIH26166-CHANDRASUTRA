import { useEffect, useMemo, useState } from "react";

import { Badge, Icon, Modal } from "./ui.jsx";
import { apiGet, apiPost } from "../api.js";
import { useAuth } from "../auth.jsx";

const TYPE_STYLE = {
  TYPE_SELECTED: { label: "reliable + selected", dot: "bg-ok", cls: "bg-ok/[0.22] border-ok/50" },
  TYPE_CONFIRMED: { label: "reliable", dot: "bg-lunar-400", cls: "bg-lunar-400/[0.18] border-lunar-400/50" },
  TYPE_NEEDS_TILES: { label: "observed · below thresholds", dot: "bg-warn", cls: "bg-warn/[0.12] border-warn/40" },
  TYPE_NOT_APPLICABLE: { label: "outer cell", dot: "bg-muted/40", cls: "bg-space-900/40 border-white/[0.06]" },
};

function gateTone(state) {
  if (state === "COMPLETE") return "ok";
  if (state === "RUNNING") return "blue";
  if (state === "BLOCKED") return "warn";
  if (state === "FAILED" || state === "INSUFFICIENT") return "warn";
  return "neutral";
}

export default function SpatialReliabilityPanel({ pairId, notify }) {
  const { canMutate } = useAuth();
  const [status, setStatus] = useState(null);
  const [summary, setSummary] = useState(null);
  const [map, setMap] = useState(null);
  const [components, setComponents] = useState(null);
  const [cells, setCells] = useState(null);
  const [selection, setSelection] = useState(null);
  const [scFields, setScFields] = useState(null);
  const [manifest, setManifest] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = useMemo(
    () => async () => {
      setError(null);
      let st = null;
      try {
        st = await apiGet(`/spatial/${pairId}/status`);
        setStatus(st);
      } catch (e) {
        setError(e);
        return;
      }
      if (st.gate_state === "COMPLETE") {
        const get = async (ep, key) => {
          try {
            const r = await apiGet(`/spatial/${pairId}/${ep}`);
            return key ? r[key] : r;
          } catch {
            return null;
          }
        };
        setSummary(await get("summary", "summary"));
        setMap(await get("map", "map"));
        setComponents(await get("components", "components"));
        setCells(await get("cells", "cells"));
        setSelection(await get("selection", "selection"));
        setScFields(await get("selected-correspondences"));
      }
    },
    [pairId]
  );

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pairId]);

  async function runSpatial() {
    setBusy(true);
    setError(null);
    try {
      const st = await apiPost(`/spatial/${pairId}/run`, {});
      setStatus(st);
      if (st.gate_state === "BLOCKED") {
        notify({
          title: `SPATIAL blocked · ${st.block_code ?? "?"}`,
          message: st.reasons?.join(", ") ?? "Blocked honestly at the spatial gate.",
          tone: "warn",
        });
      } else if (st.gate_state === "INSUFFICIENT") {
        notify({
          title: `SPATIAL insufficient · ${pairId}`,
          message: "The run completed but no validated spatial selection was possible.",
          tone: "warn",
        });
      } else if (st.gate_state === "COMPLETE") {
        notify({
          title: `Spatial Reliability complete · ${pairId}`,
          message: "Grid evidence, connected regions and reliability-aware selection were computed.",
          tone: "ok",
        });
      } else if (st.gate_state === "FAILED") {
        notify({
          title: `SPATIAL failed · ${pairId}`,
          message: "No trustworthy spatial artifact could be produced.",
          tone: "warn",
        });
      }
      await load();
    } catch (e) {
      setError(e);
      notify({ title: "SPATIAL run failed", message: e.message, tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function resetSpatial() {
    setBusy(true);
    try {
      const r = await apiPost(`/spatial/${pairId}/reset`);
      setStatus(r.status);
      setSummary(null);
      setMap(null);
      setComponents(null);
      setCells(null);
      setSelection(null);
      setScFields(null);
      notify({
        title: `${pairId} spatial reset`,
        message: "Only derived spatial artifacts were removed. M4/M3/M2 products and raw/ are untouched.",
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
      const m = (await apiGet(`/spatial/${pairId}/manifest`)).manifest;
      setManifest(m);
    } catch (e) {
      notify({ title: "No spatial manifest", message: e.message, tone: "danger" });
    }
  }

  const mapped = map?.visualization?.grid ?? null;

  return (
    <section className="space-y-4">
      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-bold text-slate-100">
                Spatial Reliability — <span className="font-mono text-lunar-300">{pairId}</span>
              </h3>
              <Badge tone={gateTone(status?.gate_state ?? "NOT_STARTED")}>
                {status?.gate_state ?? "NOT_STARTED"}
              </Badge>
            </div>
            <p className="mt-1 text-xs text-muted">
              Configuration <code className="font-mono text-slate-300">SR-M5-001</code> · overlap-normalised scene grid,
              per-cell verified evidence, neighbourhood support, connected regions and reliability-aware selection ·
              no scientific confidence claims.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-primary" disabled={busy || !canMutate} title={canMutate ? "Run spatial reliability gate" : "Analyst or admin required"} onClick={runSpatial}>
              <Icon.Activity className="h-4 w-4" /> {busy ? "Running…" : "Run SPATIAL"}
            </button>
            <button className="btn-ghost" disabled={busy || !canMutate} title={canMutate ? "Reset pair state" : "Analyst or admin required"} onClick={resetSpatial}>
              <Icon.Refresh className="h-4 w-4" /> Reset
            </button>
            <button
              className="btn-ghost"
              disabled={busy || status?.gate_state !== "COMPLETE"}
              onClick={openManifest}
              title="Spatial provenance manifest"
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
            {status.reasons?.join(", ") ?? "Spatial gate stopped honestly — no reliable scene evidence to represent."}
          </p>
        </div>
      )}
      {status?.gate_state === "INSUFFICIENT" && (
        <div className="rounded-lg border border-warn/30 bg-warn/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-warn">
            <Icon.Info className="h-3.5 w-3.5" /> INSUFFICIENT · no supported region
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            The run completed but no reliable region met the selection policy. This is a truthful, first-class
            outcome — no registration follows.
          </p>
        </div>
      )}
      {status?.gate_state === "FAILED" && (
        <div className="rounded-lg border border-danger/30 bg-danger/[0.06] p-3.5">
          <p className="flex items-center gap-2 text-xs font-bold text-danger">
            <Icon.Alert className="h-3.5 w-3.5" /> FAILED · spatial artifact unusable
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            No trustworthy spatial representation could be produced from the trusted evidence.
          </p>
        </div>
      )}

      {status?.gate_state === "COMPLETE" && summary && (
        <SpatialSummary summary={summary} selection={selection} scFields={scFields} />
      )}

      {mapped && map && (
        <SceneGrid
          grid={map.visualization.grid}
          legend={map.visualization.legend}
          selectedCellIds={map.visualization.selected_cell_ids}
          fragmentation={map.fragmentation}
          boundary={map.boundary}
        />
      )}

      {components && <ComponentExplorer components={components} />}

      {cells && <CellExplorer cells={cells} />}

      <div className="card border-warn/30 bg-warn/[0.06] p-4">
        <p className="flex items-start gap-2 text-[11px] leading-relaxed text-warn">
          <Icon.Lock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            M5 represents <strong className="text-warn">measurable spatial evidence</strong>: which cells of the overlap
            scene carry verified inliers, which reliable regions join into a supported component, and which
            correspondences were selected for registration. It is not an absolute accuracy or
            physical-registration claim — M6 consumes exactly this selection to fit, validate and warp;
            every registration diagnostic is a measurement, never scientific truth.
          </span>
        </p>
      </div>

      <Modal open={!!manifest} onClose={() => setManifest(null)} title={`Spatial manifest · ${pairId}`}>
        {manifest && (
          <pre className="max-h-[60vh] overflow-auto rounded-lg bg-space-900/70 p-3 font-mono text-[10px] leading-snug text-slate-300">
            {JSON.stringify(manifest, null, 2)}
          </pre>
        )}
      </Modal>
    </section>
  );
}

function SpatialSummary({ summary, selection, scFields }) {
  const rel = summary.reliability ?? {};
  const scene = summary.scene ?? {};
  const tiles = summary.tiles ?? {};
  const sel = selection ?? summary.selection ?? {};
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="ok">{rel.reliable_cells ?? 0} reliable cells</Badge>
        <Badge tone="blue">{rel.connected_components ?? 0} components</Badge>
        <Badge tone={sel.selected_correspondence_count ? "gold" : "warn"}>
          {sel.selected_correspondence_count ?? 0} selected correspondences
        </Badge>
        <Badge tone="neutral">{summary.selection_outcome}</Badge>
      </div>
      <p className="text-[11px] leading-relaxed text-muted">
        <span className="font-mono text-slate-300">
          {rel.scene_cells_observed ?? 0} observed / {rel.supported_cells ?? 0} supported
        </span>
        {" · "}verified inliers{" "}
        <span className="font-mono text-slate-300">{scene.verified_inlier_count ?? 0}</span> from{" "}
        <span className="font-mono text-slate-300">{scene.usable_candidates_from_trusted_tiles ?? 0}</span> trusted
        candidates across <span className="font-mono text-slate-300">{tiles.trusted_tiles ?? 0}</span> trusted tiles
        {tiles.recompute_failed ? ` · recompute failures ${tiles.recompute_failed}` : ""}
        {" · "}fragmentation{" "}
        <span className="font-mono text-slate-300">{JSON.stringify(rel.fragmentation ?? {})}</span> · runtime{" "}
        <span className="font-mono text-slate-300">{summary.runtime_seconds ?? "—"}s</span>
      </p>
      {sel.capped_at_limit && (
        <p className="text-[11px] text-warn">
          Selection hit the per-run cap of {sel.max_selected_correspondences ?? sel.limit} correspondences.
        </p>
      )}
      {scFields && (
        <p className="text-[11px] text-muted">
          selected_correspondences.npz fields:{" "}
          <span className="font-mono text-slate-300">{scFields.fields?.join(", ")}</span> ·{" "}
          <span className="font-mono text-slate-300">{scFields.component_id_count?.toString?.() ?? ""}</span> records
          carry component provenance.
        </p>
      )}
    </div>
  );
}

function SceneGrid({ grid, legend, selectedCellIds, fragmentation, boundary }) {
  const rows = grid ?? [];
  const selSet = new Set(selectedCellIds ?? []);
  const legendEntries = Object.entries(legend ?? {});
  const selectedCount = selectedCellIds?.length ?? 0;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-100">Scene reliability grid</h3>
        <div className="flex flex-wrap items-center gap-2">
          {selectedCount > 0 && <Badge tone="ok">{selectedCount} selected cell{selectedCount === 1 ? "" : "s"}</Badge>}
          <Badge tone="neutral">{rows.length}×{rows[0]?.length ?? rows.length}</Badge>
        </div>
      </div>
      <div
        className="grid gap-[2px]"
        style={{ gridTemplateColumns: `repeat(${rows[0]?.length ?? 0}, minmax(0, 1fr))` }}
      >
        {rows.flatMap((row, r) =>
          row.map((cell) => {
            const st = TYPE_STYLE[cell.state] ?? TYPE_STYLE.TYPE_NOT_APPLICABLE;
            const selected = selSet.has(cell.cell_id);
            return (
              <div
                key={`${r}-${cell.cell_id}`}
                title={`${cell.cell_id} · ${st.label}${selected ? " · selected" : ""}`}
                className={`aspect-square rounded-[3px] border ${st.cls} ${selected ? "ring-1 ring-ok/60" : ""}`}
              >
                <span className="sr-only">{cell.cell_id}</span>
              </div>
            );
          })
        )}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {legendEntries.map(([key, label]) => {
          const st = TYPE_STYLE[key] ?? TYPE_STYLE.TYPE_NOT_APPLICABLE;
          return (
            <span key={key} className="flex items-center gap-1.5 text-[10.5px] text-muted">
              <span className={`h-2 w-2 rounded-full ${st.dot}`} />
              {label}
            </span>
          );
        })}
      </div>
      {(fragmentation || boundary) && (
        <p className="text-[11px] text-muted">
          fragmentation <span className="font-mono text-slate-300">{JSON.stringify(fragmentation ?? {})}</span>
          {" · "}boundary <span className="font-mono text-slate-300">{JSON.stringify(boundary ?? {})}</span>
        </p>
      )}
    </div>
  );
}

function ComponentExplorer({ components }) {
  const comps = components.components ?? [];
  const selectedIds = components.selected_component_ids ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-100">Connected components</h3>
        <Badge tone="blue">{components.component_count ?? comps.length}</Badge>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {comps.map((c) => (
          <div
            key={c.component_id}
            className={`rounded-lg border p-3 ${
              c.selected
                ? "border-ok/30 bg-ok/[0.05]"
                : "border-white/[0.07] bg-space-900/40"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <p className="truncate font-mono text-[11px] font-semibold text-slate-200">{c.component_id}</p>
              {c.selected ? <Badge tone="ok">selected</Badge> : <Badge tone="neutral">not selected</Badge>}
            </div>
            <div className="mt-2 space-y-1 text-[10.5px] text-muted">
              <p>
                cells <span className="font-mono text-slate-300">{c.cell_count}</span> · correspondences{" "}
                <span className="font-mono text-slate-300">{c.correspondence_count}</span> · trusted tiles{" "}
                <span className="font-mono text-slate-300">{c.trusted_tile_count}</span>
              </p>
              <p>
                area proxy <span className="font-mono text-slate-300">{c.area_proxy}</span>
                {c.edge_touching ? " · edge-touching" : ""} · centroid{" "}
                <span className="font-mono text-slate-300">({c.centroid?.r}, {c.centroid?.c})</span>
              </p>
            </div>
          </div>
        ))}
        {comps.length === 0 && <p className="text-xs text-muted">No reliable cells formed a component.</p>}
        {selectedIds.length > 0 && (
          <p className="text-[11px] text-muted sm:col-span-2 lg:col-span-3">
            supported region selected: <span className="font-mono text-slate-300">{selectedIds.join(", ")}</span>
          </p>
        )}
      </div>
    </div>
  );
}

function CellExplorer({ cells }) {
  const list = cells.cells ?? [];
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-bold text-slate-100">Per-cell evidence</h3>
        <Badge tone="neutral">{list.length} cells</Badge>
      </div>
      <div className="card max-h-[420px] overflow-y-auto p-4">
        {list.length === 0 ? (
          <p className="text-xs text-muted">No cells evaluated.</p>
        ) : (
          <table className="w-full text-left text-[10.5px]">
            <thead className="sticky top-0 bg-space-950 text-muted">
              <tr>
                <th className="py-1 pr-3 font-mono font-semibold">cell</th>
                <th className="py-1 pr-3 font-semibold">state</th>
                <th className="py-1 pr-3 text-right font-semibold">inliers</th>
                <th className="py-1 pr-3 text-right font-semibold">usable</th>
                <th className="py-1 pr-3 text-right font-semibold">support</th>
                <th className="py-1 pr-3 font-semibold">component</th>
              </tr>
            </thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.cell_id} className="border-t border-white/[0.04]">
                  <td className="py-1 pr-3 font-mono text-slate-300">{c.cell_id}</td>
                  <td className="py-1 pr-3">
                    {c.selected ? (
                      <Badge tone="ok">selected</Badge>
                    ) : c.reliable ? (
                      <Badge tone="gold">reliable</Badge>
                    ) : c.observed ? (
                      <Badge tone="warn">observed</Badge>
                    ) : (
                      <Badge tone="neutral">outer</Badge>
                    )}
                  </td>
                  <td className="py-1 pr-3 text-right font-mono">{c.verified_inlier_count}</td>
                  <td className="py-1 pr-3 text-right font-mono">{c.usable_correspondence_count}</td>
                  <td className="py-1 pr-3 text-right font-mono">{c.neighbor_support}</td>
                  <td className="py-1 pr-3 font-mono text-slate-400">{c.component_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p className="sr-only">Reliability evidence per grid cell.</p>
    </div>
  );
}