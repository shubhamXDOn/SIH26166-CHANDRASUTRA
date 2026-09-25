import { useMemo } from "react";

/*
 * CHANDRA SUTRA — space-tech decorative assets.
 *
 * Purely presentational. These components draw styled SVG/CSS ornamentation
 * (stars, orbital rings, coordinate grids, scan lines) to establish the
 * cinematic research interface. They never attach numbers, labels or
 * telemetry of any kind. Anything that displays actual evidence (e.g.
 * `CorrespondenceOverlay`) renders ONLY from real coordinates supplied by the
 * caller — never fabricates imagery.
 */

/* Deterministic tiny PRNG so star fields are stable across renders. */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/* ------------------------------------------------------------- star field */

export function StarField({ count = 90, seed = 26166, className = "" }) {
  const stars = useMemo(() => {
    const rand = mulberry32(seed);
    return Array.from({ length: count }, (_, i) => ({
      id: i,
      x: Math.round(rand() * 1000) / 10,
      y: Math.round(rand() * 1000) / 10,
      r: 0.4 + rand() * 1.1,
      o: 0.25 + rand() * 0.55,
      tw: rand() > 0.72,
    }));
  }, [count, seed]);

  return (
    <svg
      className={className}
      role="presentation"
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid slice"
      viewBox="0 0 100 100"
    >
      {stars.map((s) => (
        <circle
          key={s.id}
          cx={s.x}
          cy={s.y}
          r={s.r}
          fill="#a5f0e0"
          opacity={s.o}
          className={s.tw ? "animate-pulse-soft" : undefined}
        />
      ))}
    </svg>
  );
}

/* ------------------------------------------------------------ orbital rings */

export function OrbitalRings({ className = "", accent = "#43cdb5" }) {
  return (
    <svg
      className={className}
      role="presentation"
      viewBox="0 0 600 600"
      fill="none"
      stroke={accent}
      strokeWidth="1"
    >
      <ellipse cx="300" cy="300" rx="290" ry="120" opacity="0.14" />
      <ellipse cx="300" cy="300" rx="235" ry="96" opacity="0.20" strokeDasharray="3 7" />
      <ellipse cx="300" cy="300" rx="180" ry="74" opacity="0.26" />
      <ellipse cx="300" cy="300" rx="128" ry="52" opacity="0.34" strokeDasharray="2 6" />
    </svg>
  );
}

/* ----------------------------------------------------------- coordinate grid */

export function CoordinateGrid({ className = "", accent = "#74e2cc" }) {
  const lines = useMemo(() => {
    const out = [];
    for (let i = 0; i <= 12; i += 1) {
      const y = (i / 12) * 100;
      out.push(<line key={`h${i}`} x1="0" y1={y} x2="100" y2={y} />);
      const x = (i / 12) * 100;
      out.push(<line key={`v${i}`} x1={x} y1="0" x2={x} y2="100" />);
    }
    return out;
  }, []);

  return (
    <svg className={className} role="presentation" viewBox="0 0 100 100" fill="none" stroke={accent}>
      {lines}
    </svg>
  );
}

/* --------------------------------------------------------------- lunar disc */

export function LunarDisc({ className = "", size = 260 }) {
  return (
    <div
      className={`pointer-events-none select-none ${className ?? ""}`}
      style={{ width: size, height: size }}
      aria-hidden
    >
      <svg viewBox="0 0 200 200" width={size} height={size}>
        <defs>
          <radialGradient id="csLunarGlow" cx="38%" cy="34%" r="75%">
            <stop offset="0%" stopColor="#b5efe0" />
            <stop offset="45%" stopColor="#5abfa9" />
            <stop offset="78%" stopColor="#123a38" />
            <stop offset="100%" stopColor="#081018" />
          </radialGradient>
          <filter id="csLunarBloom" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="14" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <g filter="url(#csLunarBloom)">
          <circle cx="100" cy="100" r="78" fill="url(#csLunarGlow)" />
          <circle cx="152" cy="62" r="16" fill="#0e2a28" opacity="0.85" />
          <circle cx="60" cy="140" r="11" fill="#0e2a28" opacity="0.7" />
          <circle cx="128" cy="148" r="7" fill="#0e2a28" opacity="0.6" />
          <circle cx="72" cy="66" r="9" fill="#0e2a28" opacity="0.55" />
        </g>
      </svg>
    </div>
  );
}

/* ---------------------------------------------------------------- scan line */

export function ScanLine({ className = "" }) {
  return (
    <div className={`pointer-events-none relative overflow-hidden ${className ?? ""}`} aria-hidden>
      <div className="animate-scan absolute left-0 h-px w-full bg-gradient-to-r from-transparent via-teal-300/70 to-transparent" />
    </div>
  );
}

/* -------------------------------------------------------- orbital background */

export function OrbitalBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 overflow-hidden" aria-hidden>
      <StarField className="absolute inset-0 h-full w-full opacity-70" />
      <OrbitalRings className="animate-drift absolute right-[-18%] top-[-16%] h-[70vh] w-[70vh] max-w-none opacity-60" />
      <CoordinateGrid className="absolute inset-x-0 bottom-0 h-[46vh] w-full opacity-[0.05]" accent="#74e2cc" />
      <div className="absolute bottom-[-22vh] left-[-12vw] h-[55vh] w-[55vh] rounded-full bg-teal-700/15 blur-3xl" />
      <div className="absolute right-[-8vw] top-[18%] h-[40vh] w-[40vh] rounded-full bg-cyan-600/10 blur-3xl" />
      <div className="absolute bottom-[6%] right-[4%] hidden opacity-[0.08] xl:block">
        <OrbitalRings className="h-[34vh] w-[34vh]" accent="#74e2cc" />
      </div>
    </div>
  );
}

/* ---------------------------------------------------- correspondence overlay
 * Renders real evidence only: crosses at the given source/destination points
 * plus connector lines. Renders nothing when no points are supplied, so a
 * blocked/empty stage can never show fabricated correspondence imagery. */

export function CorrespondenceOverlay({
  pairs = [],
  className = "",
  sourceColor = "#43cdb5",
  targetColor = "#33b7dc",
  lineColor = "#1dab97",
}) {
  if (!Array.isArray(pairs) || pairs.length === 0) return null;

  const W = 100;
  const H = 56.25;
  const denomX = 100;
  const denomY = 100;

  return (
    <svg
      className={className}
      role="presentation"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      fill="none"
    >
      {pairs.map((p, i) => {
        if (!p || !Array.isArray(p.src) || !Array.isArray(p.dst)) return null;
        const sx = (p.src[0] / denomX) * W;
        const sy = (p.src[1] / denomY) * H;
        const dx = (p.dst[0] / denomX) * W;
        const dy = (p.dst[1] / denomY) * H;
        if (Number.isNaN(sx + sy + dx + dy)) return null;
        return (
          <g key={i} opacity="0.85">
            <line x1={sx} y1={sy} x2={dx} y2={dy} stroke={lineColor} strokeWidth="0.25" opacity="0.5" />
            <g stroke={sourceColor} strokeWidth="0.5">
              <line x1={sx - 1.4} y1={sy} x2={sx + 1.4} y2={sy} />
              <line x1={sx} y1={sy - 1.4} x2={sx} y2={sy + 1.4} />
            </g>
            <circle cx={dx} cy={dy} r="0.9" stroke={targetColor} strokeWidth="0.4" />
          </g>
        );
      })}
    </svg>
  );
}

/* ------------------------------------------------------------- mission stamp */

export function MissionStamp({ className = "" }) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border border-teal-400/25 bg-teal-500/5 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.22em] text-teal-300/90 ${className ?? ""}`}
    >
      <span className="relative inline-flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-teal-400 opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-teal-400" />
      </span>
      SIH·26166 Orbital Research
    </span>
  );
}