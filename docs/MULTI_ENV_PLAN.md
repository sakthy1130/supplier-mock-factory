# Multi-Environment Support (dev + stg, default dev) — IMPLEMENTED

> Goal: run SMF against **dev** and **stg**, defaulting to **dev**, with a **live env toggle in the UI** (no restart to switch). Implemented via per-request env selection (contextvar) + env-tagged scenarios. Status: done and tested (backend 152/153 unit tests passing — the 1 failure is a pre-existing live-staging integration test unrelated to this change).

## Actual implementation vs. original plan (read this first)

The plan below (steps 1–12) was written before implementation. One decision changed
significantly for the better once step 1 was underway:

**Step 3 ("inject Settings into every client") was NOT needed.** Every integration
client (`BackofficeClient`, `MockServerClient`, `CrawlaClient`, etc.) already does
`self.settings = get_settings()` fresh at `__init__` time, and every client is
constructed per-call (never cached/reused across requests). Making `get_settings()`
fall back to a **contextvar** (`app/env_context.py`) when no explicit `env` is passed
means setting that contextvar at the right boundary — request middleware for
synchronous request-time calls, `with use_env(record.env):` for scenario lifecycle
background jobs — automatically threads the correct env through every client with
**zero changes to the clients themselves**. This cut the largest planned chunk of work
to near-zero and is the key architectural takeaway if this is extended later (e.g. a
third `prod` env, or per-tenant settings): prefer a contextvar over threading a config
object through constructors when every consumer already reads settings fresh per call.

Everything else below matches what was actually built.

## Why this is non-trivial

Everything env-specific flows through **one file** — `backend/.env` — loaded by [config.py](../backend/app/config.py) as a process-wide singleton. There is no concept of "environment"; the values just happen to be staging. A live toggle means settings can no longer be a singleton, and every scenario must remember which env created it so lifecycle ops hit the right env after the dropdown changes.

### Env-specific surface today

| Group | Where | Examples |
|---|---|---|
| Service URLs (9) | `backend/.env` | `MOCK_SERVER_URL`, `BACKOFFICE_URL`, `CRAWLA_API_URL`, `CONFIG_MANAGER_URL`, `MAPPING_SERVICE_URL`, `QUICKWIT_LOGS_API_URL`, `LOGS_API_URL`, `CORE_APP_URL`, `BUSINESS_RULES_URL` |
| Hardcoded URL defaults (2) | [config.py:25-26](../backend/app/config.py#L25) | `core_app_url`, `business_rules_url` default to `…tajawal-staging.internal` |
| Creds / keys | `backend/.env` | `BACKOFFICE_USERNAME/PASSWORD`, `MAPPING_API_KEY`, `CRAWLA_API_KEY`, `TENANT_ID` |
| Reference IDs | `backend/.env` | `HBS/EXP/RHK/CHC_REFERENCE_CONTRACT_ID`, `API_KEY_TEMPLATE_UID` |
| **Hardcoded staging data** | [supplier_registry.py](../backend/app/core/supplier_registry.py) (`supplier_id`, `auto_id`), [quickwit_indices.py](../backend/app/core/quickwit_indices.py) (index naming), the scenario store (SQLite `smf.db`, now MongoDB) | Baked into code, not env |

Two traps beyond URLs:
- **`supplier_registry.py`** — supplier_id/auto_id are staging Mongo ids; dev almost certainly differs. Must become env-aware or provisioning creates broken contracts.
- **`smf.db`** stores each scenario's contract ids + apiKey. Create in stg then switch to dev → teardown sends stg ids to dev Backoffice → fails. Scenarios must be pinned to their env.

## Plan (checklist) — all done

### Backend

- [x] **1. Settings registry, not singleton.** `get_settings(env=None)` in [config.py](../backend/app/config.py) — `@lru_cache`'d per env via internal `_build_settings(env)`, loaded from legacy `.env` → `.env.shared` → `.env.{env}` (later wins). Default resolved from the contextvar (`dev`). Hardcoded staging URL defaults removed (`core_app_url`/`business_rules_url` now `""`, set per env file).
- [x] **2. Env travels with the request.** [main.py](../backend/app/main.py) `env_context_middleware` reads `X-SMF-Env`, sets the contextvar (`app/env_context.py`) for the request, resets in `finally`. Response echoes `X-SMF-Env-Resolved` for debugging.
- [x] ~~3. Inject settings into clients~~ **Not needed** — see "Actual implementation" above. Contextvar fallback in `get_settings()` covers every client transparently.
- [x] **4. Env-aware supplier registry.** [supplier_registry.py](../backend/app/core/supplier_registry.py) — `get_supplier_registry(env=None)`; `_DEV_REGISTRY = _STG_REGISTRY` (same ids, confirmed) but structurally split so a future divergence is a one-line change.
- [x] **5. Tag every scenario with its env.** `ScenarioRecord.env` column (migration backfills existing rows as `stg`). `create_pending(db, request, env=None)` persists it. `run_create_scenario`, `run_refresh_booking_ids`, `_teardown_record` all wrap the orchestrator call in `with use_env(record.env):` — never the caller's current env.
- [x] **6. Quickwit index per env.** [quickwit_indices.py](../backend/app/core/quickwit_indices.py) — `resolve_console_logs_index(env, ...)` takes env directly (dev/stg share one URL): dev→`dev`, stg→`staging` prefix, `prod`→monthly format kept for future use.
- [x] **7. Env metadata endpoints.** `GET /health` includes `env`; new `GET /api/env` returns `{available, default, current}` ([app/api/routes/env.py](../backend/app/api/routes/env.py)).

### Frontend

- [x] **8. Env dropdown in header.** Sidebar `.env-switcher` in [App.tsx](../frontend/src/App.tsx), dev default, persisted via `localStorage` in [base.ts](../frontend/src/api/base.ts) (`getActiveEnv`/`setActiveEnv`).
- [x] **9. API client attaches `X-SMF-Env`.** `envHeaders()` in `base.ts`, wired into all 4 fetch wrappers (`client.ts`, `scenarios.ts`, `crawla.ts`) plus `hotels.ts` (mapping service is env-specific). `testRun.ts` deliberately excluded — Java test-run tracking is env-agnostic.
- [x] **10. Scenario list filtered by active env**; env badge on list rows ([ScenarioList.tsx](../frontend/src/components/ScenarioList.tsx)) and the detail `id-badge` (App.tsx). `?env=all` bypasses the filter.

### Wiring & tests

- [x] **11.** `.env.shared` / `.env.dev` / `.env.stg` (+ `.example`s), `docker-compose.yml` (bind-mounts the 3 files — `env_file:` can't preserve per-env distinctness inside one container), README/AGENTS runbook.
- [x] **12.** New [test_multi_env.py](../backend/tests/test_multi_env.py) (env normalization, settings layering, `/health` + `/api/env`, create/list/teardown-all scoped by env) + fixes to existing tests broken by the `get_settings.cache_clear()` → `clear_settings_cache()` rename and the quickwit-index signature change.

## Decisions (defaulted — change if needed)

- **One DB with an `env` column** (not two DB files) — lets the list filter by env and keeps teardown correct via stored env.
- **Backfill migration**: existing `smf.db` rows get `env = stg`.
- **Default env = dev** everywhere (backend dependency default + frontend initial state).

## Dev values RECEIVED

### Service URLs (dev)

| key | dev value |
|---|---|
| `MOCK_SERVER_URL` | `http://mockserver-dev.tajawal.io` |
| `BACKOFFICE_URL` | `http://enigma-portal-dev.almosafer.com` |
| `CONFIG_MANAGER_URL` | `http://hotels-connectivity-config.tajawal-dev.internal/` |
| `CRAWLA_API_URL` | `http://alm-crawla-realtime-api-dev.alm-data.io` |
| `MAPPING_SERVICE_URL` | `http://hotels-integration-mapping-service.tajawal-dev.internal` |
| `QUICKWIT_LOGS_API_URL` | `http://quickwit-nonprod.tajawal-prod-devops.internal/api/v1` (SAME as stg) |
| `LOGS_API_URL` | `https://enigma-logs-dev.almosafer.com/` |
| `CORE_APP_URL` | `http://hotels-connectivity-core.tajawal-dev.internal` |
| `BUSINESS_RULES_URL` | `http://hotel-connectivity-br.tajawal-dev.internal` |

### Quickwit index nuance (affects step 6)

Dev + stg share the same Quickwit **URL**, so the index cannot be chosen by URL anymore.
`resolve_console_logs_index` must take the **env** and map:
- dev → `hotels-consolelogs-dev-YYYY_MM_DD`
- stg → `hotels-consolelogs-staging-YYYY_MM_DD`
- prod → `hotels-consolelogs-prod-apps-YYYY_MM` (keep URL-based prod check as fallback)

## Dev values used (all received)

| # | Value | Source |
|---|---|---|
| 1 | Service URLs (9) | provided directly, in `.env.dev` |
| 2 | `TENANT_ID` | `6239b84f15f94102b50f4a29` |
| 2 | Backoffice user/pass | `sakthivel.sunder@almosafer.com` / provided |
| 2 | `MAPPING_API_KEY`, `CRAWLA_API_KEY` | same as stg → moved to `.env.shared` |
| 3 | Reference contracts (HBS/EXP/RHK/CHC) + `API_KEY_TEMPLATE_UID` | same as stg → `.env.shared` (HBS/RHK/template were already unset in stg too — minimal-body fallback applies to both envs equally) |
| 4 | Supplier registry (`supplier_id`/`auto_id`) | same as stg → `_DEV_REGISTRY = _STG_REGISTRY` |
| 5 | Quickwit dev index | same URL as stg, prefix `hotels-consolelogs-dev-`, daily `YYYY_MM_DD` — confirmed |
| 6 | Network | dev on the same VPN as stg — confirmed |

**Known risk:** items 3 and 4 assume dev shares stg's Backoffice/Mongo records. If dev
turns out to have its own Backoffice DB, the first dev scenario create will fail at
contract-clone time (404 on `EXP_REFERENCE_CONTRACT_ID`) or produce a contract with a
supplier_id Backoffice doesn't recognize. Fix is localized: put real dev ids in
`.env.dev` (overrides `.env.shared`) and/or populate `_DEV_REGISTRY` in
`supplier_registry.py` with dev-specific values — no other code changes needed.

## Follow-ups / not done

- **No live smoke test against real dev/stg infra** was run as part of this change
  (would create real contracts/apiKeys on shared infra) — verified via mocked-orchestrator
  unit tests + a local TestClient/uvicorn check of `/health`, `/api/env`, and the DB
  migration only. First real dev scenario create is the real end-to-end proof.
- **Concurrent same-namespace collision across envs** was not specifically addressed:
  namespace uniqueness is enforced globally (`ScenarioRecord.namespace` unique
  constraint) even though HBS mock paths are per-supplier-shared-canonical, not
  per-namespace — this was already true pre-multi-env and is unchanged.
- **`prod` env** is scaffolded in `quickwit_indices.py`'s index resolution (monthly
  format) but not in `SUPPORTED_ENVS` — add `"prod"` there plus a `.env.prod` if ever
  needed; the contextvar/middleware/lifecycle-pinning mechanism needs no other change.
