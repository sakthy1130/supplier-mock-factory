# Supplier Mock Factory (SMF) — Architecture

QA automation tool for hotel-connectivity testing. It stands up fake ("mock")
hotel suppliers so QA can exercise the booking platform against controlled,
predictable supplier responses instead of hitting real suppliers.

## Pipeline

```
real SIDs → templates → scenario mutations → MockServer → contracts → fresh apiKey → READY
```

One API call creates a fully isolated, bookable test environment; one call tears
it all down.

## Stack (locked)

| Layer    | Choice |
|----------|--------|
| Backend  | Python 3.12, FastAPI, Pydantic v2, httpx, SQLAlchemy + SQLite |
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, shadcn/ui |
| External | MockServer, backoffice/config-manager APIs, Quickwit (logs) |
| Do NOT add | Java runtime, MongoDB, callback host service |

## Repository layout

```
supplier-mock-factory/
├── backend/
│   └── app/
│       ├── api/routes/     # scenarios, crawla, suppliers, hotels, logs, admin, health, test_run
│       ├── core/           # orchestrator + engine + provisioners + per-supplier paths
│       ├── integrations/   # all external HTTP (mock_server, backoffice, config_manager, quickwit)
│       ├── plugins/        # per-supplier logic: hbs.py, exp.py, rhk.py, chc.py
│       ├── ingest/         # build templates from real Enigma adapter logs
│       ├── models/         # Pydantic ScenarioRequest, ScenarioBundle, Crawla models
│       ├── services/       # scenario_service (SQLite + background jobs), caches, quickwit
│       └── db/             # SQLite models
├── frontend/src/           # App.tsx, api/, components/ (wizards, list, progress, result), hooks/
├── templates/{HBS,EXP,RHK,CHC}/{LogType}/v1.json
├── field-maps/{HBS,EXP,RHK,CHC}.json
├── scripts/                # ingest_sids.py, quickwit_search.py
└── docs/                   # ARCHITECTURE.md, PROGRESS.md, RESUME.md, HANDOFF*, CRAWLA_MOCKS_*
```

## Domain model

- **Suppliers (4):** HBS (Hotelbeds), EXP (Expedia), RHK (RateHawk/WorldOTA), CHC (Choice/Derby BTS)
- **Log types (7):** Search, Packages, CancellationPolicy, PreBooking, Booking, GetOrder, CancelOrder
- **Contract types:** net suppliers (HBS, CHC, RHK) borrow the market price
  (`dynamicMarketType = DynamicMarkupTarget`); gross suppliers (EXP) provide it
  (`MarketPriceSource`)

## Core flow — `create_scenario`

`SupplierMockScenarioOrchestrator.create_scenario` ([backend/app/core/orchestrator.py](backend/app/core/orchestrator.py))
drives the scenario through explicit status transitions on a `ScenarioBundle`:

1. **BUILDING_MOCKS** — `ScenarioEngine.build_expectations` loads per-supplier
   templates and mutates them (dates, hotel ids, prices, room names, currency,
   refundability, package linkage).
2. **REGISTERING** — `register_built_expectations` posts expectations to
   MockServer (path + method only at register, `priority: 1000`) and returns
   injected booking ids.
3. **CREATING_CONTRACTS** — `ContractProvisioner.create_contracts` clones a
   reference contract per supplier, points its URL opts at the mock base, and
   applies supplier-specific defaults/currency.
4. **(optional) SB group + config** — for Smart Booking scenarios, created
   *before* the apiKey so they can be injected into `opt.smartBooking` at
   apiKey-create time (post-create PUT corrupts the record).
5. **CREATING_API_KEY** — `ApiKeyProvisioner.create_api_key` mints a fresh
   apiKey and attaches the contracts. **Never reuse shared test keys.**
6. **(optional) Business Rules** — provisioned for crawla-export and all SB scenarios.
7. **READY** — bundle carries apiKey, contract ids, booking ids, mock base URL.

`refresh_booking_ids` re-injects fresh booking ids without rebuilding;
`teardown_scenario` removes mocks + contracts + apiKey by namespace id.

## Key invariants

- **Namespace isolation** — every expectation id is
  `smf-{namespace}-{supplier}-{logType}`. Teardown is id-based; no header
  matchers on `httpRequest`.
- **Package linkage** — rateKey / hashes / net / boardCode must stay synced
  across Search → Packages → PreBooking. Mismatch causes adapter price errors
  (e.g. HBS `E3021.1`). Enforced by `propagate_package_linkage` +
  `linkage_validator`.
- **Fresh apiKey per scenario** — isolation and clean teardown.
- **BookingIdInjector** — the same booking id appears in Booking + GetOrder +
  CancelOrder; refreshable via API.
- **Hotel id resolution** — UI sends the **ATG hotel id**; the backend resolves
  per-supplier ids via `GET /v2/supplier/{supplierCode}/{atgHotelId}`. Mocks use
  supplier ids; core search uses ATG.
- **Body matchers** — ingest/templates use `ONLY_MATCHING_FIELDS` with `header`
  stripped; runtime registration matches path + method only.

## Ingest

`backend/app/ingest/` builds templates from real Enigma adapter logs (by SID).
`expectation_builder.py` extracts response/request payloads, resolves path +
method, and emits `ONLY_MATCHING_FIELDS` body matchers. CLI:
`python scripts/ingest_sids.py --input reference-sids.json`.

## Per-supplier notes

- **HBS** — canonical mock paths (`hbs_paths.py`); contract url opts
  (`searchUrl`, `availabilityUrl`, …); refundability tuned so NRF/REF render
  correctly on the adapter.
- **EXP** — gross supplier; paths taken from built expectations; `override*Url`
  contract opts.
- **RHK** — WorldOTA B2B v3 paths; `match_hash`/`book_hash` linkage;
  `partner_order_id` as booking id; meal mapping RO/BB/HB/FB.
- **CHC** — newest supplier; `roomId`/`rateId`/`roomCriteria` linkage;
  `chc_paths.py` forces `isCancellationPolicyOneSlot: true`; net supplier, so it
  takes `DynamicMarkupTarget` (like HBS) to participate in package-merge.

## API surface

| Method | Path | Notes |
|--------|------|-------|
| GET  | `/health` | status, phase |
| POST | `/api/scenarios` | create (202, background job) |
| GET  | `/api/scenarios` | list |
| GET  | `/api/scenarios/{id}` | bundle + status |
| POST | `/api/scenarios/{id}/refresh-booking-ids` | re-inject booking ids |
| DELETE | `/api/scenarios/{id}` | teardown: mocks + contracts + apiKey |
| DELETE | `/api/scenarios/all` | clear all active scenarios |
| GET  | `/api/scenarios/{id}/quickwit-logs` | runtime logs by scenario apiKey |
| POST | `/api/logs/quickwit/search` | generic Quickwit search |
| GET  | `/api/suppliers` | supplier metadata |
| —    | `/api/crawla`, `/api/hotels`, `/api/test-run`, `/api/admin` | Crawla mocks, hotel mapping, test-run dashboard, admin |

## Frontend

React SPA (`frontend/src/`): `App.tsx` hosts Create + Browse tabs and a
Clear-all action. Wizards (`ScenarioWizard`, `CrawlaMocksWizard`,
`CrawlaQueueRunner`), status views (`ScenarioProgress`, `ScenarioResult`,
`ScenarioList`), and `TestRunDashboard`. `useScenarioPoll` polls status until
READY. API layer under `src/api/` proxies to the backend on `:8000`.

## Runtime logs (Quickwit)

`app/integrations/quickwit.py` (port of Java `QuickwitLogsActivator`) searches
staging console logs by scenario apiKey. Index auto-resolves to
`hotels-consolelogs-staging-YYYY_MM_DD`. Requires VPN/internal network.

## Run locally

```bash
# backend
cd backend && source ../.venv/bin/activate
PYTHONPATH=. python -m uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm run dev   # :5173 → proxy :8000
```

## Current state

Branch `crawla-e2e-package-level`, **Phase P9** — multi-supplier package-level
mocks (per-package currency, room names, refundable) across HBS + EXP + RHK +
CHC. P0–P8 complete. See `docs/PROGRESS.md` for the live session handoff and
`docs/HANDOFF_CLAUDE.md` for detail.
