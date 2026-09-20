# CHANDRASUTRA — Deployment Guide (v1.0.0)

Deploys the M13 final release stack: a FastAPI backend serving both the API and
the release/evidence endpoints, a Vite-built React frontend behind nginx, and a
shared, persistent data volume holding raw data, derived artifacts and the
frozen evidence package.

> **Hosting status for this release: NOT_AVAILABLE.** No public URL was
> provisioned from the offline development environment. This guide documents
> how to deploy and self-host locally or on your own infrastructure; actual
> hosted latency has **not** been measured and is **not** estimated anywhere
> in this release.

---

## 1. Topology

```
                        ┌───────────────────────────┐
public :80  ──► nginx  ──► frontend (static, Vite)  │
                        └────────────┬──────────────┘
                                      │  /api  ──► backend (api only)
gateway  ──► :8000 ──► uvicorn ──► FastAPI app
                        └──── volumes: chandrasutra_data:/data (persistent)
```

- **backend** — `backend/Dockerfile`, runs the FastAPI app on port 8000.
- **frontend** — `frontend/Dockerfile`, builds the app and serves it with
  nginx on port 80.
- **volume `chandrasutra_data`** — `/data` (the app data root). Must contain
  (as appropriate): `raw/`, `metadata/`, `derived/`, `auth/`,
  `final_evidence/`, `reports/`.

## 2. Prerequisites

- Docker Engine + Compose v2 (tested here with Docker 29.7.2).
- A `.env` file (see section 4) with a **non-default** `AUTH_SECRET_KEY` and
  bootstrap admin credentials.
- Optional but recommended for a full demo: a seeded evidence package
  (`scripts/m13_release_prep.py`, section 5) so the Evidence page and
  `POST /api/m13/demo/reset` have real frozen content to verify.

## 3. Quick start

```bash
# 1. configure secrets (never commit .env)
cp .env.example .env
#    edit: AUTH_SECRET_KEY, AUTH_BOOTSTRAP_ADMIN_USERNAME, AUTH_BOOTSTRAP_ADMIN_PASSWORD

# 2. (recommended) seed the frozen evidence + report centre into ./data
python scripts/m13_release_prep.py --data-root data

# 3. validate the compose file
docker compose config -q || docker compose config

# 4. build and start
docker compose up -d --build

# 5. verify
curl -s http://localhost:8000/api/health      # {"status":"ok", ...}
# open http://localhost:80  → sign in with the bootstrap admin.
```

## 4. Environment variables

All secrets come from `.env` (`.env.example` documents every variable).
Critical ones:

| Variable | Meaning | Release default |
| --- | --- | --- |
| `APP_ENV` | `development \| demo \| production \| test` | `production` (compose) |
| `APP_VERSION` | engineering build identity (M11 config stage id — **do not change**) | `0.11.0` |
| `DEMO_MODE` | show an explicit persistent synthetic marker | `false` |
| `AUTH_SECRET_KEY` | JWT signing secret — **set a strong random value** | from `.env` |
| `AUTH_BOOTSTRAP_ADMIN_USERNAME` / `_PASSWORD` | first admin created at boot | from `.env` |
| `AUTH_REGISTER_ENABLED` | public self-registration | `true` (set `false` for closed jury runs) |
| `DATA_ROOT` | mounted volume path | `/data` |
| `GEMINI_API_KEY` | M9 AI provider (not configured in this release) | empty |

> **Why `APP_VERSION` must stay `0.11.0`:** the M12 configuration freeze
> records `app_version` as the M11 operations stage identity. Changing it
> would make `verify_configuration_freeze` report DRIFT and break the
> `VERIFIED` evidence status. The release version `1.0.0` is exposed
> separately and never enters the frozen fingerprint.

## 5. Seeding the frozen evidence

```bash
python scripts/m13_release_prep.py --data-root data
```

This copies the released experiment package byte-for-byte into
`data/final_evidence/`, copies the mileage report centre into `data/reports/`,
copies the measurements record into `data/reports/m13_performance.json`, and
**re-verifies every seeded package**. The command exits non-zero if any seeded
package fails re-verification — a release must never ship a broken package.
(It ignores superseded experiment folders that fail verification upstream.)

## 6. Verify the deployment

| Check | Command | Expect |
| --- | --- | --- |
| Compose validity | `docker compose config -q` | exit 0 |
| Health | `curl -s localhost:8000/api/health` | `status=ok` |
| Auth | sign in on `:80` | session ok |
| Release status | `curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/m13/status` | `evidence.verify_status=VERIFIED` |
| Evidence explorer | Evidence page → experiment card | package + manifest + provenance |
| Report centre | Evidence page → report list → open a report | markdown view |
| Demo reset | Evidence page → “Reset demonstration” | toast “frozen evidence re-verified untouched” |
| Measurements | `GET /api/m13/measurements` | local `MEASURED_LOCALLY`, hosted `NOT_MEASURED` |

## 7. Operations notes

- **Backups:** the whole scientific state lives in `chandrasutra_data`.
  Back up `/data` (including `final_evidence/`) and the `.env` file together.
- **HTTPS:** put the stack behind a TLS-terminating reverse proxy
  (nginx/Caddy). Never expose `:8000` directly in production.
- **Restart policy:** compose sets `restart: unless-stopped`.
- **Frozen evidence is read-only:** the API never writes to `final_evidence`.
  `POST /api/m13/demo/reset` only re-verifies and reports state.
- **Jury runs:** set `AUTH_REGISTER_ENABLED=false`, `APP_ENV=demo` (keeps the
  fingerprints intact because demo/environment fields are not part of the
  M11 operations digest), provision the seeded volume, and present via the
  Evidence page.

## 8. Limitations stated honestly

- No public host was provisioned; this guide validates the stack locally.
- Hosted latency is `NOT_MEASURED`; the measurements endpoint only reports the
  local runtime medians.
- Real mission data remains gated (PATH B) until official PRADAN access is
  onboarded (`REAL_DATA_ONBOARDING.md`).