/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        /*
         * CHANDRA SUTRA — mission design system.
         * Foundation: near-black with a faint cool teal cast.
         * Illumination: restrained teal/green; cyan as secondary accent.
         * Legacy token names (space/lunar/orbit/ok/warn/danger/muted) are kept
         * so existing components resolve, but their VALUES are remapped to the
         * new palette.
         */
        space: {
          950: "#030709",
          900: "#060b10",
          850: "#081018",
          800: "#0a141c",
          750: "#0d1a23",
          700: "#11222e",
          600: "#17303f",
        },
        // primary illumination — teal/green (was gold). Name kept for compat.
        lunar: {
          200: "#a5f0e0",
          300: "#74e2cc",
          400: "#43cdb5",
          500: "#1dab97",
          600: "#15877a",
          700: "#11615c",
        },
        // secondary accent — cyan (was blue).
        orbit: {
          300: "#a3e9fb",
          400: "#62d4f2",
          500: "#33b7dc",
          600: "#1f8fb4",
        },
        // semantic status tokens
        ok: "#38d69c",
        warn: "#e8b25c",
        danger: "#f26d6d",
        blocked: "#c98a3d",
        abstain: "#6f7d8a",
        muted: "#75858f",
        // alias scales so text-teal-* / text-cyan-* resolve to mission colors
        teal: {
          200: "#a5f0e0",
          300: "#74e2cc",
          400: "#43cdb5",
          500: "#1dab97",
          600: "#15877a",
          700: "#11615c",
        },
        cyan: {
          300: "#a3e9fb",
          400: "#62d4f2",
          500: "#33b7dc",
          600: "#1f8fb4",
        },
        // fully-earmarked mission tokens (goal: a single central palette)
        mission: {
          background: "#030709",
          surface: "#081018",
          "surface-elevated": "#0d1a23",
          border: "#1a3a3f",
          "text-primary": "#e7f4f0",
          "text-secondary": "#b0c4cb",
          "text-muted": "#75858f",
          teal: "#1dab97",
          cyan: "#33b7dc",
          green: "#38d69c",
          warning: "#e8b25c",
          danger: "#f26d6d",
          blocked: "#c98a3d",
          abstain: "#6f7d8a",
          glow: "rgba(29,171,151,0.35)",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(29,171,151,0.28), 0 8px 30px -8px rgba(29,171,151,0.35)",
        "glow-cyan": "0 0 0 1px rgba(51,183,220,0.28), 0 8px 30px -8px rgba(51,183,220,0.30)",
        card: "0 18px 50px -14px rgba(0,0,0,0.65)",
        panel: "inset 0 1px 0 0 rgba(255,255,255,0.04)",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          from: { backgroundPosition: "200% 0" },
          to: { backgroundPosition: "-200% 0" },
        },
        "spin-slow": {
          to: { transform: "rotate(360deg)" },
        },
        scan: {
          "0%": { top: "0%", opacity: "0" },
          "8%": { opacity: "1" },
          "92%": { opacity: "1" },
          "100%": { top: "100%", opacity: "0" },
        },
        drift: {
          "0%": { transform: "translate3d(0,0,0)" },
          "50%": { transform: "translate3d(-0.5%,0.5%,0)" },
          "100%": { transform: "translate3d(0,0,0)" },
        },
      },
      animation: {
        "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
        "fade-up": "fade-up 0.4s cubic-bezier(0.22,1,0.36,1) both",
        shimmer: "shimmer 1.8s linear infinite",
        "spin-slow": "spin-slow 2.6s linear infinite",
        scan: "scan 6s ease-in-out infinite",
        drift: "drift 90s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};