# SIH26166 configuration

`configs/app.yaml` holds **engineering placeholders** for the future
scientific pipeline. M0 defines the framework only; there are no scientific
thresholds yet.

Rules:

- Runtime and secrets (`APP_ENV`, `CORS_ORIGINS`, `AUTH_SECRET_KEY`,
  `GEMINI_API_KEY`, ...) live in environment variables or `.env`, never here
  and never in source code. See `.env.example`.
- Experimentally tuned parameters will only be introduced together with real
  data, a valid **Pair ID** and a **Configuration ID**.
- Editing a config value to change an outcome is prohibited by scientific
  integrity policy (see `README.md`).
- Configurations must be reproducible: the config file that produced a result
  is recorded alongside that result.