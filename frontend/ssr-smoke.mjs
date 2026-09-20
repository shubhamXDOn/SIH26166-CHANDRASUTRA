/**
 * Headless runtime render smoke — catches component crashes (bad imports,
 * undefined components, invalid hooks during render) without a browser.
 *
 * Uses Vite's SSR module loader to transform and execute the real JSX, then
 * server-renders every page with react-dom. Effects/API calls do not run
 * during SSR, so this validates the render path only.
 *
 * Run:  node ssr-smoke.mjs
 */
import React from "react";
import { renderToString } from "react-dom/server";
import { createServer } from "vite";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const server = await createServer({
  root,
  logLevel: "silent",
  server: { middlewareMode: true },
  appType: "custom",
});

const results = {};
let failCount = 0;

try {
  const modules = {
    App: (await server.ssrLoadModule("/src/App.jsx")).default,
    AuthProvider: (await server.ssrLoadModule("/src/auth.jsx")).AuthProvider,
    AuthCtx: (await server.ssrLoadModule("/src/auth.jsx")).AuthCtx,
    Overview: (await server.ssrLoadModule("/src/pages/Overview.jsx")).default,
    Evidence: (await server.ssrLoadModule("/src/pages/Evidence.jsx")).default,
    Data: (await server.ssrLoadModule("/src/pages/Data.jsx")).default,
    Analysis: (await server.ssrLoadModule("/src/pages/Analysis.jsx")).default,
    Results: (await server.ssrLoadModule("/src/pages/Results.jsx")).default,
    AIInsights: (await server.ssrLoadModule("/src/pages/AIInsights.jsx")).default,
    Settings: (await server.ssrLoadModule("/src/pages/Settings.jsx")).default,
    Account: (await server.ssrLoadModule("/src/pages/Account.jsx")).default,
    Security: (await server.ssrLoadModule("/src/pages/Security.jsx")).default,
    Sidebar: (await server.ssrLoadModule("/src/components/Sidebar.jsx")).Sidebar,
    RegistrationPanel: (await server.ssrLoadModule("/src/components/RegistrationPanel.jsx")).default,
    MetricsPanel: (await server.ssrLoadModule("/src/components/MetricsPanel.jsx")).default,
    SpatialReliabilityPanel: (await server.ssrLoadModule("/src/components/SpatialReliabilityPanel.jsx")).default,
    TrustPanel: (await server.ssrLoadModule("/src/components/TrustPanel.jsx")).default,
    Pipeline: (await server.ssrLoadModule("/src/components/Pipeline.jsx")).default,
    M8Workspace: (await server.ssrLoadModule("/src/components/M8Workspace.jsx")).default,
  };

  const authedUser = {
    id: "U-x",
    username: "smoke-admin",
    display_name: "Smoke Admin",
    role: "admin",
    is_active: true,
    created_at: "2026-09-18T00:00:00+00:00",
    updated_at: "2026-09-18T00:00:00+00:00",
    last_login_at: "2026-09-18T00:00:00+00:00",
  };

  // Pages that render the sign-in gate on boot need the auth provider to exist;
  // pages that read the session need a fully-resolved authed value.
  const withBooting = (node) =>
    React.createElement(modules.AuthProvider, null, node);
  const withAuthed = (node) =>
    React.createElement(
      modules.AuthCtx.Provider,
      {
        value: {
          status: "authed",
          user: authedUser,
          auth: { authentication_enabled: true, registration_enabled: true },
          isAdmin: true,
          canMutate: true,
          signIn: async () => {},
          signUp: async () => {},
          signOut: async () => {},
        },
      },
      node
    );

  const renderMap = {
    app: React.createElement(modules.App),
    Overview: React.createElement(modules.Overview, {
      backend: { online: true },
      onNavigate() {},
      notify() {},
    }),
    Evidence: React.createElement(modules.Evidence, { notify() {} }),
    Data: withBooting(
      React.createElement(modules.Data, { notify() {} })
    ),
    Analysis: withBooting(React.createElement(modules.Analysis)),
    Results: React.createElement(modules.Results),
    AIInsights: React.createElement(modules.AIInsights),
    Settings: React.createElement(modules.Settings),
    Account: withAuthed(React.createElement(modules.Account, { notify() {} })),
    Security: withAuthed(React.createElement(modules.Security, { notify() {} })),
    Sidebar: withAuthed(
      React.createElement(modules.Sidebar, {
        page: "overview",
        onNavigate() {},
        backend: { online: true, environment: "development", version: "0.10.0" },
      })
    ),
    RegistrationPanel: withBooting(
      React.createElement(modules.RegistrationPanel, {
        pairId: "CS-P001",
        notify() {},
      })
    ),
    MetricsPanel: withBooting(
      React.createElement(modules.MetricsPanel, {
        pairId: "CS-P001",
        notify() {},
      })
    ),
    SpatialReliabilityPanel: withBooting(
      React.createElement(modules.SpatialReliabilityPanel, {
        pairId: "CS-P001",
        notify() {},
      })
    ),
    TrustPanel: withBooting(
      React.createElement(modules.TrustPanel, {
        pairId: "CS-P001",
        notify() {},
      })
    ),
    Pipeline: React.createElement(modules.Pipeline, {
      stages: [
        { id: "register", label: "Register", desc: "Transform fit & warp", state: "ready" },
        { id: "metrics", label: "Metrics", desc: "Reproducible reports", state: "locked" },
      ],
      onStageClick() {},
    }),
    M8Workspace: withBooting(
      React.createElement(modules.M8Workspace, {
        pairId: "CS-P001",
        notify() {},
      })
    ),
  };

  for (const [name, element] of Object.entries(renderMap)) {
    results[name] = renderToString(element).length;
  }
} catch (err) {
  console.error(`FATAL render error: ${err.stack || err}`);
  await server.close();
  process.exit(1);
}

await server.close();

for (const [name, len] of Object.entries(results)) {
  // "app" renders in the auth booting state during SSR — the splash is tiny.
  const min = name === "app" ? 80 : 200;
  const ok = len > min;
  console.log(`${ok ? "PASS" : "FAIL"}  ssr render ${name}: ${len} chars`);
  if (!ok) failCount += 1;
}
console.log(failCount === 0 ? "OVERALL: PASS" : `OVERALL: FAIL (${failCount})`);
process.exitCode = failCount === 0 ? 0 : 1;