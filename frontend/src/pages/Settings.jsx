import { useEffect, useState } from "react";

import { Badge, Icon, PageSkeleton } from "../components/ui.jsx";
import { apiGet } from "../api.js";

const ENV_REFERENCE = [
  { key: "GEMINI_API_KEY", purpose: "Backend-only Gemini key (never exposed to the browser)", secret: true },
  { key: "AUTH_SECRET_KEY", purpose: "Signing secret for access tokens; empty = auth not configured", secret: true },
  { key: "APP_ENV", purpose: "development | production", secret: false },
  { key: "APP_DEBUG", purpose: "enables /api/docs and verbose logging", secret: false },
  { key: "BACKEND_HOST / BACKEND_PORT", purpose: "Uvicorn bind target", secret: false },
  { key: "CORS_ORIGINS", purpose: "Comma-separated allowed browser origins", secret: false },
  { key: "LOG_LEVEL", purpose: "Python logging level", secret: false },
];

function Row({ k, v }) {
  return (
    <tr>
      <td className="font-mono text-xs text-slate-200">{k}</td>
      <td className="max-w-[220px] truncate text-xs text-muted" title={String(v)}>{v === "" ? "—" : String(v)}</td>
    </tr>
  );
}

export default function Settings() {
  const [meta, setMeta] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    apiGet("/meta")
      .then((m) => alive && setMeta(m))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, []);

  if (!meta) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Settings</h2>
        <PageSkeleton rows={3} />
        {error && (
          <p className="flex items-center gap-2 text-sm text-danger">
            <Icon.Alert className="h-4 w-4" /> {error.message}
          </p>
        )}
      </div>
    );
  }

  const s = meta.settings;

  return (
    <div className="space-y-6">
      <section className="max-w-3xl space-y-2">
        <h2 className="text-xl font-extrabold tracking-tight text-slate-100 sm:text-2xl">Settings</h2>
        <p className="text-sm leading-relaxed text-muted">
          Runtime view of the backend. Secret values never leave the server; only presence is
          reported. Edit environment variables in <code className="font-mono text-slate-300">.env</code>{" "}
          (see <code className="font-mono text-slate-300">.env.example</code>).
        </p>
      </section>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-100">Runtime configuration</h3>
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <Row k="app_name" v={meta.application} />
                <Row k="app_version" v={meta.version} />
                <Row k="app_env" v={s.app_env} />
                <Row k="app_debug" v={s.app_debug} />
                <Row k="log_level" v={s.log_level} />
                <Row k="data_root" v={s.data_root} />
                <Row k="cors_origins" v={(s.cors_origins || []).join(", ")} />
              </tbody>
            </table>
          </div>
        </div>

        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-100">Capabilities</h3>
          <ul className="space-y-3 text-sm">
<li className="flex items-center justify-between gap-3">
                <span className="text-muted">Authentication</span>
                {s.auth?.configured ? (
                  <Badge tone="ok">configured</Badge>
                ) : (
                  <Badge tone="warn">not configured</Badge>
                )}
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">AI / Gemini</span>
                {s.ai?.configured ? (
                  <Badge tone="ok">configured</Badge>
                ) : (
                  <Badge tone="warn">not configured</Badge>
                )}
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">AI service</span>
                <Badge tone="blue">{s.ai?.service ?? "—"}</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Token algorithm</span>
                <span className="font-mono text-xs text-slate-200">{s.auth?.algorithm ?? "—"}</span>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Milestone</span>
                <Badge tone="gold">{meta.milestone ?? "M1"} — Real Data &amp; Metadata</Badge>
              </li>
              <li className="flex items-center justify-between gap-3">
                <span className="text-muted">Scientific matching</span>
                <Badge tone="neutral">NOT_RUN in M1</Badge>
              </li>
            </ul>
            <div className="mt-4 rounded-lg border border-white/[0.06] bg-space-900/50 p-3 text-xs leading-relaxed text-muted">
              <p className="flex items-center gap-1.5 text-warn">
                <Icon.Info className="h-3.5 w-3.5" /> Engineering note
              </p>
              <p className="mt-1">
                No scientifically tuned thresholds exist yet. M1 handles real data and metadata;
                preprocessing, matching and configuration IDs arrive in M2+.
              </p>
            </div>
          </div>
        </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-100">M1 — data &amp; metadata configuration</h3>
          <div className="overflow-x-auto">
            <table className="table-base">
              <thead>
                <tr>
                  <th>Key</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <Row k="allowed_raw_locations" v={(meta.m1_config?.allowed_raw_locations || []).join(", ")} />
                <Row k="pairs.json" v={meta.m1_config?.pairs_json_rel} />
                <Row k="pairs.csv" v={meta.m1_config?.pairs_csv_rel} />
                <Row k="validation record" v={meta.m1_config?.validation_record_rel} />
                <Row k="parser_require_pds4_label" v={String(meta.m1_config?.parser_require_pds4_label)} />
                <Row k="unknown_fill" v={meta.m1_config?.unknown_fill} />
                <Row k="hash_algorithm" v={meta.m1_config?.hash_algorithm} />
                <Row k="preview_max_width" v={String(meta.m1_config?.preview_max_width)} />
                <Row k="preview_dir" v={meta.m1_config?.preview_dir_rel} />
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-muted">Loaded from <code className="font-mono text-slate-300">configs/app.yaml</code> (m1 section).</p>
        </div>

        <div className="card p-5">
          <h3 className="mb-3 text-sm font-bold text-slate-100">Data &amp; pair semantics</h3>
          <ul className="space-y-2.5 text-sm">
            <li className="flex items-center justify-between gap-3">
              <span className="text-muted">Raw products</span>
              <Badge tone="blue">immutable · hashed</Badge>
            </li>
            <li className="flex items-center justify-between gap-3">
              <span className="text-muted">Pair IDs</span>
              <span className="font-mono text-xs text-slate-200">CS-P001, CS-P002, …</span>
            </li>
            <li className="flex items-center justify-between gap-3">
              <span className="text-muted">Known-overlap evidence</span>
              <Badge tone={meta.settings?.app_env ? "warn" : "neutral"}>requires documentation</Badge>
            </li>
            <li className="flex items-center justify-between gap-3">
              <span className="text-muted">Source</span>
              <Badge tone="blue">ISSDC PRADAN</Badge>
            </li>
          </ul>
        </div>
      </div>

      <div className="card p-5">
        <h3 className="mb-3 text-sm font-bold text-slate-100">Environment reference</h3>
        <div className="overflow-x-auto">
          <table className="table-base">
            <thead>
              <tr>
                <th>Variable</th>
                <th>Purpose</th>
                <th className="w-24">Secret</th>
              </tr>
            </thead>
            <tbody>
              {ENV_REFERENCE.map((row) => (
                <tr key={row.key}>
                  <td className="font-mono text-xs text-slate-200">{row.key}</td>
                  <td className="max-w-sm text-xs leading-relaxed text-muted">{row.purpose}</td>
                  <td>
                    {row.secret ? (
                      <Badge tone="warn">yes — never exposed</Badge>
                    ) : (
                      <Badge tone="neutral">no</Badge>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}