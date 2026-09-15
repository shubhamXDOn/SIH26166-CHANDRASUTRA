import { useEffect, useState } from "react";

import { Badge, EmptyState, Icon, PageSkeleton, StatusDot } from "../components/ui.jsx";
import { apiGet } from "../api.js";

export default function Data({ notify }) {
  const [status, setStatus] = useState(null);
  const [sensors, setSensors] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([apiGet("/data/status"), apiGet("/data/sensors")])
      .then(([s, sen]) => {
        if (!alive) return;
        setStatus(s);
        setSensors(sen);
      })
      .catch((e) => {
        if (!alive) return;
        setError(e);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) return <PageSkeleton rows={3} />;

  if (error || !status) {
    return (
      <div className="card p-6">
        <p className="flex items-center gap-2 text-sm font-semibold text-danger">
          <Icon.Alert className="h-4 w-4" /> Unable to access the configured scientific data source.
        </p>
        <p className="mt-1 text-xs text-muted">{String(error?.message ?? error)}</p>
        <button className="btn-ghost mt-4" onClick={() => window.location.reload()}>
          <Icon.Refresh className="h-4 w-4" /> Retry
        </button>
      </div>
    );
  }

  const byId = Object.fromEntries(status.directories.map((d) => [d.id, d]));
  const rawDirs = status.directories.filter((d) => d.is_raw);
  const derivedDirs = status.directories.filter((d) => !d.is_raw);

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl space-y-2">
          <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">
            Data readiness
          </h2>
          <p className="text-sm leading-relaxed text-muted">
            The scientific data architecture is staged. Raw imagery stays immutable; every derived
            product is reproducible from raw + configuration. No pair is registered in M0.
          </p>
        </div>
        <Badge tone="warn">
          <StatusDot state="warn" /> Awaiting M1 real-data integration
        </Badge>
      </section>

      {/* Pairs banner */}
      <div className="card flex items-start gap-3 p-4">
        <Icon.Info className="mt-0.5 h-4 w-4 shrink-0 text-lunar-400" />
        <div className="text-sm">
          <p className="font-semibold text-slate-100">
            Registered pairs: {status.pairs_registered}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {status.pairs_note}
          </p>
        </div>
      </div>

      {/* Sensors */}
      <section className="space-y-3">
        <h3 className="text-sm font-bold text-slate-100">Phase-A sensors — Chandrayaan-2</h3>
        <div className="grid gap-4 md:grid-cols-2">
          {(sensors?.phase_a ?? []).map((s) => (
            <div key={s.id} className="card card-hover p-4">
              <div className="mb-1 flex items-center gap-2">
                <Badge tone="blue">{s.id}</Badge>
              </div>
              <p className="text-sm font-bold text-slate-100">{s.name}</p>
              <p className="mt-1 text-xs text-muted">{s.kind}</p>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-300">{s.role}</p>
            </div>
          ))}
        </div>
        <p className="text-[11px] leading-relaxed text-muted">
          {sensors?.note}
        </p>
      </section>

      {/* Directory table */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-slate-100">Directory architecture</h3>
          <span className="font-mono text-xs text-muted">{status.root}</span>
        </div>

        <div className="card overflow-x-auto">
          <table className="table-base whitespace-nowrap">
            <thead>
              <tr>
                <th>Logical location</th>
                <th>Purpose</th>
                <th>Class</th>
                <th>On disk</th>
              </tr>
            </thead>
            <tbody>
              {status.directories.map((d) => (
                <tr key={d.id}>
                  <td className="font-mono text-xs text-slate-200">{d.path}</td>
                  <td className="max-w-xs truncate text-xs text-muted" title={d.description}>
                    {d.description}
                  </td>
                  <td>
                    <Badge tone={d.is_raw ? "gold" : "neutral"}>
                      {d.is_raw ? "raw · immutable" : "derived"}
                    </Badge>
                  </td>
                  <td>
                    {d.exists ? (
                      <span className="flex items-center gap-1.5 text-xs font-medium text-ok">
                        <Icon.Check className="h-3.5 w-3.5" /> present
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 text-xs text-muted">
                        <Icon.Lock className="h-3.5 w-3.5" /> awaiting
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="card p-4">
            <p className="mb-2 text-xs font-bold uppercase tracking-wider text-lunar-400">
              Raw — immutable by design
            </p>
            <ul className="space-y-1.5 text-xs leading-relaxed text-muted">
              <li>· Never read-modify-write: no transform writes back to <code className="font-mono text-slate-300">data/raw</code>.</li>
              <li>· Unknown metadata stays UNKNOWN — never fabricated.</li>
              <li>· {Object.keys(byId).length} logical locations · {rawDirs.length} raw, {derivedDirs.length} derived.</li>
            </ul>
          </div>
          <div className="card p-4">
            <p className="mb-2 text-xs font-bold uppercase tracking-wider text-orbit-400">
              Derived — reproducible
            </p>
            <ul className="space-y-1.5 text-xs leading-relaxed text-muted">
              <li>· Every derived artifact is rebuildable from raw + configuration.</li>
              <li>· Pair ID / Configuration ID labels arrive with results.</li>
              <li>· No manual editing of correspondence points or outputs — ever.</li>
            </ul>
          </div>
        </div>

        <div className="card p-4">
          <p className="mb-1 flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-100">
            <Icon.Database className="h-4 w-4 text-lunar-400" /> Official data source
          </p>
          <ul className="space-y-1 text-xs leading-relaxed text-muted">
            <li>
              ISRO / ISSDC PRADAN (Planetary Data Archive for Chandrayaan-2) —{" "}
              <a className="text-orbit-300 underline decoration-orbit-500/40 underline-offset-2 hover:text-orbit-200" href="https://pradan.issdc.gov.in/" target="_blank" rel="noreferrer">
                pradan.issdc.gov.in
              </a>
            </li>
            <li>
              Chandrayaan-2 data —{" "}
              <a className="text-orbit-300 underline decoration-orbit-500/40 underline-offset-2 hover:text-orbit-200" href="https://pradan.issdc.gov.in/ch2/" target="_blank" rel="noreferrer">
                pradan.issdc.gov.in/ch2
              </a>
            </li>
          </ul>
          <button
            className="btn-ghost mt-3 !px-3 !py-1.5 text-xs"
            onClick={() => notify({ title: "M1 scope", message: "The first documented OHRC–TMC-2 pair is acquired in M1 — deliberately not downloaded yet.", tone: "ok" })}
          >
            Acquisition plan
          </button>
        </div>
      </section>
    </div>
  );
}