# SMF Progress — Session Handoff

> **Update this file at the end of every Cursor session.** New agents read this first.

## Current phase

**P8 — Crawla Mocks** ✅ COMPLETE

## Last updated

2026-06-10

## Last session summary

### ATG → supplier hotel mapping
- UI field: **ATG hotel ID** (was supplier hotel id)
- Backend: `HotelMappingClient` → `GET /v2/supplier/{supplierCode}/{atgHotelId}`
- `GET /api/hotels/mapping` — preview supplier ids in wizard
- Mocks use per-supplier `supplier_hotel_ids`; bundle shows ATG + supplier ids
- Config: `MAPPING_SERVICE_URL`, `MAPPING_API_KEY` in `.env`

### Quickwit integration
- `app/integrations/quickwit.py` — search client (port `QuickwitLogsActivator`)
- `app/core/quickwit_indices.py` — staging/prod index name resolution
- `GET /api/scenarios/{id}/quickwit-logs` — search by scenario api_key
- `POST /api/logs/quickwit/search` — generic search
- `scripts/quickwit_search.py` — CLI
- Config: `QUICKWIT_LOGS_API_URL` in `.env`

### Clear-all mock wipe
- `DELETE /api/scenarios/all` now does per-scenario teardown plus a final full MockServer expectation wipe
- `MockServerClient.delete_all_expectations()` added for bulk clear fallback
- Fix ensures Clear all data removes SMF-created mocks even if id-based namespace teardown misses leftovers
- Focused backend tests pass:
  - `backend/tests/test_mock_server.py`
  - `backend/tests/test_scenario_service_teardown.py`

### HBS GetOrder confirmed mock
- HBS `GetOrder` supplier mock now normalizes booking status to `CONFIRMED`
- Template source updated:
  - `templates/HBS/GetOrder/v1.json`
- Runtime mutation updated:
  - `backend/app/plugins/hbs.py`
- Regression test added:
  - `backend/tests/test_plugins_p2.py`

### HBS GetOrder path fix
- HBS `GetOrder` mock path now appends the injected booking id at runtime:
  - `/hotel-api/1.2/bookings/GetOrderBooking/{booking_id}`
- Booking-id injection now preserves HBS `GetOrder` path semantics after template finalization
- Focused backend tests pass:
  - `backend/tests/test_booking_id_injector.py`
  - `backend/tests/test_hbs_paths.py`
  - `backend/tests/test_contract_provisioner.py`

### Codex baseline (Cursor parity)
- `AGENTS.md` — layout, caveman rules, ingest extract modes, HBS/EXP supplier notes, API table
- `.codex/config.toml` — `project_doc_max_bytes`, `file_opener=cursor`, sandbox
- `docs/AGENTS.md` — pointer to PROGRESS + ARCHITECTURE
- `~/.codex/config.toml` — `supplier-mock-factory` trust entry

### Clear-all teardown (UI + API)
- `DELETE /api/scenarios/all` — bulk teardown all active scenarios (202 + background job)
- Teardown now removes MockServer expectations (tolerant id delete), backoffice contracts, apiKeys
- Sidebar **Clear all data** button with confirm dialog (`App.tsx`)
- `clearAllScenarios()` in `frontend/src/api/scenarios.ts`
- Backend: `BackofficeClient.delete_contract`, `delete_api_key`; `TeardownAllResponse` model

### P6 React UI
- `frontend/src/api/` — `client.ts`, `scenarios.ts` (POST/GET/refresh/teardown)
- `frontend/src/types/scenario.ts` — mirrors backend Pydantic models
- `frontend/src/hooks/useScenarioPoll.ts` — poll every 2s until READY/FAILED/TORN_DOWN
- `frontend/src/components/ScenarioWizard.tsx` — namespace, dates, hotel, HBS+EXP packages
- `frontend/src/components/ScenarioProgress.tsx` — pipeline step indicator
- `frontend/src/components/ScenarioResult.tsx` — apiKey, contracts, booking_ids + copy
- `frontend/src/components/ScenarioList.tsx` — scenario history from SQLite
- `frontend/src/App.tsx` — Create + Browse tabs, wired to `/api/scenarios`
- Vite proxy unchanged (`:5173` → `:8000`)
- `npm run build` passes

### P7 Docker + runbook polish
- `docker-compose.yml` now runs backend with `uvicorn --reload` and frontend with Vite dev server
- Backend healthcheck hits `/health` before frontend starts
- `README.md` now has compose startup steps and a QA runbook
- `docs/ARCHITECTURE.md` and `.cursor/rules/smf.mdc` now say id-based namespace isolation + `DELETE /api/scenarios/all`
- `backend/app/api/routes/health.py` phase badge updated to `P7`

### P8 Crawla Mocks
- Added `Crawla Mocks` third tab in `frontend/src/App.tsx`
- `frontend/src/components/CrawlaMocksWizard.tsx` fetches live anchors from `minPriceFlexible` and `hotelPage`
- Added Crawla API client + models in backend: `app/integrations/crawla.py`, `app/models/crawla.py`
- `POST /api/crawla/anchor/search` and `POST /api/crawla/anchor/packages` proxy Crawla anchor APIs
- `POST /api/crawla/scenarios` builds HBS + EXP scenario, with bucket pricing and EXP exclude mode for `ONLY_CRAWLA`
- `ScenarioResult` now renders `crawla_export` JSON when present
- Backend scenario pipeline now accepts supplier mutations and Crawla export metadata
- `backend/app/api/routes/health.py` phase badge updated to `P8`
- Validation passed:
  - `npm run build`
  - `PYTHONPATH=. .venv/bin/pytest tests/test_crawla_mutations.py -q`
  - `python3 -X pycache_prefix=/tmp -m py_compile ...` on changed backend files

### HBS contract + mock path fix
- `app/core/hbs_paths.py` — canonical Hotelbeds roots (1.0 search/packages/prebook, 1.2 booking flow) + per-log-type MockServer suffix
- HBS contract `opt`: `searchUrl`, `availabilityUrl`, `prebookingUrl`, `bookingUrl`, `orderUrl`, `cancelBookingUrl` on mock base
- Mock expectations: path rewritten at register (e.g. `/hotel-api/1.0/hotels/search`, `/hotel-api/1.2/bookings/GetOrderBooking`)
- Backend tests: **51 passing**

### P6 UI polish (beautify)
- Dark theme: DM Sans + JetBrains Mono, gradient background (`index.css`)
- Sidebar shell: brand, nav, backend health stats (`App.css` + `App.tsx`)
- Wizard: sectioned form, supplier tiles (HBS/EXP accent colors)
- Horizontal provisioning pipeline stepper with pulse indicator
- Result panel: success banner, copy rows, meta grid, action buttons
- Browse: split list/detail layout, status pills, empty states
- Responsive breakpoints at 900px

### UI flows
1. **Create** — wizard → POST → poll progress → result with copy buttons
2. **Browse** — list scenarios → select → detail + poll if in-flight
3. **Actions** — refresh booking IDs, teardown (when READY), clear all (sidebar)

### Backend tweak
- `/health` phase badge → `P7`

### Tests
- Backend: **47 tests** (unchanged)
- Frontend: TypeScript build verified

---

## Phase checklist

| Phase | Description | Status |
|-------|-------------|--------|
| P0 | Bootstrap, docs, rules, health API, frontend shell | ✅ Done |
| P1 | Template ingest from reference SIDs (HBS + EXP) | ✅ Done |
| P2 | Scenario engine + linkage validator + plugins | ✅ Done |
| P3 | BookingId injector + MockServer register/delete | ✅ Done |
| P4 | Contract + apiKey provisioner + orchestrator | ✅ Done |
| P5 | Full REST API + SQLite + background jobs | ✅ Done |
| P6 | React UI (wizard, progress, results, list) | ✅ Done |
| P7 | docker-compose, runbook | ✅ Done |
| P8 | Crawla Mocks tab, Crawla anchors, export JSON | ✅ Done |

---

## Next session — copy into agent prompt

```
P8 complete. If more Crawla tuning is needed, start from docs/CRAWLA_MOCKS_SPEC.md and docs/PROGRESS.md.
```

---

## In progress

P8 complete. No active feature phase.

---

## Blockers

| Blocker | Owner | Notes |
|---------|-------|-------|
| Live create from UI | User | Requires backend `.env` staging creds + templates ingested |

---

## Key file paths

| Path | Purpose |
|------|---------|
| `frontend/src/App.tsx` | Main UI shell |
| `frontend/src/components/ScenarioWizard.tsx` | Create form |
| `frontend/src/hooks/useScenarioPoll.ts` | Status polling |
| `backend/app/api/routes/scenarios.py` | REST API |
| `backend/app/services/scenario_service.py` | Jobs + SQLite |

---

## Run locally

```bash
# Terminal 1 — API
cd supplier-mock-factory/backend
source .venv/bin/activate   # once per terminal (or use python3 -m uvicorn below)
PYTHONPATH=. python3 -m uvicorn app.main:app --reload --port 8000

# Terminal 2 — UI
cd supplier-mock-factory/frontend
npm run dev
```

Open http://localhost:5173

---

## Decisions locked (do not change without user approval)

- Python FastAPI + React — no Java in this repo
- HBS + EXP v1, all 7 log types
- New apiKey per scenario
- Namespace via expectation `id`
- Mock expectations: path + method only
- EXP contracts: `override*Url` fields
- SQLite scenario history

---

## Git / commits

| Commit | Phase |
|--------|-------|
| (initial) | P0 bootstrap |
| (pending) | P1–P8 |

---

## Reference: qaBackend_Enigma Java paths

```
src/main/java/com/hotels/utils/enigma/core/mockServerWrapper/CreateExpectationWrapper.java
src/main/java/com/hotels/utils/enigma/core/ContractsSupplier.java
```
