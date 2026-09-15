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
    Overview: (await server.ssrLoadModule("/src/pages/Overview.jsx")).default,
    Data: (await server.ssrLoadModule("/src/pages/Data.jsx")).default,
    Analysis: (await server.ssrLoadModule("/src/pages/Analysis.jsx")).default,
    Results: (await server.ssrLoadModule("/src/pages/Results.jsx")).default,
    AIInsights: (await server.ssrLoadModule("/src/pages/AIInsights.jsx")).default,
    Settings: (await server.ssrLoadModule("/src/pages/Settings.jsx")).default,
  };

  const renderMap = {
    app: React.createElement(modules.App),
    Overview: React.createElement(modules.Overview, {
      backend: { online: true },
      onNavigate() {},
      notify() {},
    }),
    Data: React.createElement(modules.Data, { notify() {} }),
    Analysis: React.createElement(modules.Analysis),
    Results: React.createElement(modules.Results),
    AIInsights: React.createElement(modules.AIInsights),
    Settings: React.createElement(modules.Settings),
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
  const ok = len > 200;
  console.log(`${ok ? "PASS" : "FAIL"}  ssr render ${name}: ${len} chars`);
  if (!ok) failCount += 1;
}
console.log(failCount === 0 ? "OVERALL: PASS" : `OVERALL: FAIL (${failCount})`);
process.exitCode = failCount === 0 ? 0 : 1;