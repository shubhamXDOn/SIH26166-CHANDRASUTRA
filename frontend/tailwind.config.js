/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        space: {
          950: "#04060b",
          900: "#070b14",
          850: "#0a0f1c",
          800: "#0d1423",
          750: "#101a2e",
          700: "#14203a",
          600: "#1b2a4c",
        },
        lunar: {
          200: "#fbe7c0",
          300: "#f7d79a",
          400: "#efc070",
          500: "#e6b157",
          600: "#c9923a",
          700: "#a6742c",
        },
        orbit: {
          300: "#9cc5ff",
          400: "#6faeff",
          500: "#4f94f0",
          600: "#3a76c9",
        },
        ok: "#3ddc97",
        warn: "#f0b45c",
        danger: "#ff6b6b",
        muted: "#8a97ad",
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
        glow: "0 0 0 1px rgba(230,177,87,0.25), 0 8px 30px -8px rgba(230,177,87,0.25)",
        card: "0 10px 40px -12px rgba(0,0,0,0.55)",
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
      },
      animation: {
        "pulse-soft": "pulse-soft 2.4s ease-in-out infinite",
        "fade-up": "fade-up 0.4s cubic-bezier(0.22,1,0.36,1) both",
        shimmer: "shimmer 1.8s linear infinite",
        "spin-slow": "spin-slow 2.6s linear infinite",
      },
    },
  },
  plugins: [],
};