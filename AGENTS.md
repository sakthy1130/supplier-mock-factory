# Supplier Mock Factory (SMF) — Agent instructions

File-based session continuity. Chat does not persist. **Codex and Cursor share this baseline.**

## Start every session

1. Read `docs/PROGRESS.md` — current phase + **Next session** block
2. Read `docs/ARCHITECTURE.md` — full spec
3. Implement **only** current phase tasks from PROGRESS
4. Update `docs/PROGRESS.md` before ending (checklist, summary, blockers, next prompt)

## Resume prompt

```
Resume Supplier Mock Factory (SMF).
Read: docs/ARCHITECTURE.md, docs/PROGRESS.md, .cursor/rules/smf.mdc
Continue "Next session" in PROGRESS.md only.
```

---

## Communication — caveman mode

Respond terse like smart caveman. Technical substance stays. Fluff dies.

- Drop: articles, filler (just/really/basically), pleasantries, hedging
- Fragments OK. Short synonyms. Technical terms exact. **Code/commits/PRs written normal.**
- Pattern: `[thing] [action] [reason]. [next step].`
- Not: "Sure! I'd be happy to help."
- Yes: "Bug in auth middleware. Fix:"

**Intensity:** `/caveman lite|full|ultra|wenyan` — stop with `stop caveman` or `normal mode`

**Auto-clarity:** drop caveman for security warnings, irreversible actions, user confused. Resume after.

---

## Stack (locked)

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, FastAPI, Pydantic v2, httpx, SQLAlchemy + SQLite |
| Frontend | React 18, Vite, TypeScript, Tailwind CSS, shadcn/ui |
| **Do NOT add** | Java runtime, MongoDB, callback host service |

---

## Project layout

```
supplier-mock-factory/
├── AGENTS.md                 # this file (Codex + Cursor baseline)
├── .codex/config.toml        # project Codex overrides (trusted repo required)
├── .cursor/rules/smf.mdc     # Cursor mirror of SMF rules
├── backend/
│   ├── app/
│   │   ├── api/routes/       # FastAPI (scenarios, crawla, suppliers, hotels, logs, admin, health)
│   │   ├── core/             # orchestrator, scenario_engine, hbs_paths, namespace
│   │   ├── integrations/     # mock_server, backoffice, config_manager, logs_api
│   │   ├── plugins/          # hbs.py, exp.py, rhk.py
│   │   ├── ingest/           # template_ingestor, expectation_builder
│   │   ├── models/           # Pydantic ScenarioRequest, ScenarioBundle, Crawla models
│   │   ├── services/         # scenario_service (SQLite + background jobs)
│   │   └── db/               # SQLite models
│   ├── tests/
│   └── .env.example
├── frontend/src/
│   ├── App.tsx               # Create + Browse tabs, Clear all button
│   ├── api/                  # client.ts, scenarios.ts
│   ├── components/           # Wizard, Progress, Result, List
│   └── hooks/useScenarioPoll.ts
├── templates/{HBS,EXP,RHK}/{LogType}/v1.json
├── field-maps/{HBS,EXP,RHK}.json
├── scripts/ingest_sids.py
├── reference-sids.json.example
└── docs/
    ├── PROGRESS.md           # session handoff (read first)
    ├── ARCHITECTURE.md
    └── RESUME.md
```

**Java reference (read-only):** `../src/main/java/com/hotels/utils/enigma/core/mockServerWrapper/`

---

## Architecture rules

- Port Enigma integration from qaBackend_Enigma Java — reference only, no Java dependency
- Templates: `templates/{HBS,EXP,RHK}/{LogType}/v1.json`
- Field maps: `field-maps/{HBS,EXP,RHK}.json`
- **Namespace isolation:** expectation `id` = `smf-{namespace}-{supplier}-{logType}` (id-based teardown; no header matcher on httpRequest)
- MockServer `priority`: 1000
- Request body matcher (ingest/templates): `ONLY_MATCHING_FIELDS`, strip `header` from request JSON
- Runtime mocks: path + method only (no body matcher at register)
- **New apiKey per scenario** — never reuse shared test keys
- **BookingIdInjector:** same id in Booking + GetOrder + CancelOrder; refresh via API

---

## Ingest extract modes

P1 ingest (`backend/app/ingest/expectation_builder.py`) builds templates from Enigma adapter logs.

| Function | What it extracts |
|----------|------------------|
| `extract_response_body_payload` | `response.body` dict preferred; else whole `response`; else full log |
| `extract_request_payload_for_mock` | `request.body` → `httpRequest.body` → `requestBody` / `payload`; strips `header` |
| `resolve_http_path_and_method` | Cascade: `path`, `requestPath`, `request.path`, URL parse, depth-4 path scan |
| `extract_confirmed_get_order_distributor_res_id` | `reservations[].reservationIds.distributorResId` where `status=confirmed` |
| `mock_server_json_body_matcher` | JSON matcher with `ONLY_MATCHING_FIELDS` + header strip (ingest only) |

**Log type aliases:** `prebooking`→PreBooking, `cancelorder`→CancelOrder, `getorderresponse`→GetOrder, etc.

**Optional template:** CancellationPolicy may be absent without ingest warning.

**CLI ingest:** `python scripts/ingest_sids.py --input reference-sids.json` (needs `reference-sids.json` from `.example`)

---

## Supplier notes (HBS + EXP + RHK)

### Shared (v1)

- Suppliers: **HBS**, **EXP**, **RHK**
- Log types (7): Search, Packages, CancellationPolicy, PreBooking, Booking, GetOrder, CancelOrder
- Plugins: `backend/app/plugins/hbs.py`, `exp.py`, `rhk.py`
- CancellationPolicy optional for ingest (RHK often absent)

### HBS (Hotelbeds)

- Adapter source match: `hotel-connectivity-hbs-adapter`
- Date fields: `checkIn`, `checkOut`, `rateKey` (pipe-delimited, dates embedded)
- **Mock paths** (`app/core/hbs_paths.py`): canonical roots + suffix per log type  
  e.g. `/hotel-api/1.0/hotels/search`, `/hotel-api/1.2/bookings/GetOrderBooking`
- **Contract opt:** `searchUrl`, `availabilityUrl`, `prebookingUrl`, `bookingUrl`, `orderUrl`, `cancelBookingUrl` on mock base
- **Contract opt defaults required:** `availabilityTimeoutSeconds: 50`, boolean flags as real JSON bools (not strings) — else adapter ClassCastException
- **Hotel ids:** UI sends **ATG hotel id**; backend resolves per-supplier ids via `GET /v2/supplier/{supplierCode}/{atgHotelId}`; mocks use supplier ids (e.g. HBS `156652`), core search uses ATG (e.g. `1446194`)
- **Linkage critical:** `propagate_package_linkage` syncs packages → prebook → search (rateKey, net, boardCode, single room) — mismatch causes `E3021.1` price errors
- Packages mutation collapses to **single room** (`hotel["rooms"] = [room]`)

### EXP

- Adapter source match: `hotels-exp-adapter-service-staging`
- Date fields: `checkInDate`, `checkOutDate`; URL query `checkin` / `checkout`
- **Contract opt:** `overrideSearchUrl`, `overridePackagesUrl`, `overrideBookingUrl`, `overrideRetrieveBookingUrl`, `overrideCancelBookingUrl`
- Paths taken from built expectations (not canonical HBS roots)

### RHK (RateHawk / WorldOTA)

- Adapter source match: `hotels-rhk-adapter-service-staging` (any source with `rhk` + `adapter`)
- Reference SID: `019c724b-d833-7ad1-85c7-a36e32babfcd` in `reference-sids.json`
- **Mock paths** (from ingested templates): WorldOTA B2B v3 e.g. `/api/b2b/v3/search/serp/hotels/`, `/api/b2b/v3/serp/prebook/`, `/api/b2b/v3/hotel/order/booking/finish/`, `/api/b2b/v3/hotel/order/info/`, `/api/b2b/v3/hotel/order/cancel/`
- **Contract opt:** `searchUrl`, `availabilityUrl`, `prebookingUrl`, `bookingUrl`, `orderUrl`, `cancelBookingUrl` (same field names as HBS-style net contracts, not EXP overrides)
- **Reference contract:** `RHK_REFERENCE_CONTRACT_ID=663a2b3267e9f7646696be28` (`rhk-sandbox-new-flow` — matches serp/prebook flow)
- **Supplier registry:** `supplier_id=652cd63a90fb03102f226030`, `auto_id=100671`
- **Hotel ids:** mapping `GET /v2/supplier/RHK/{atgHotelId}` → numeric `hid` for mocks
- **Package linkage:** `match_hash` / `book_hash` synced packages → prebook → search
- **Booking id:** `partner_order_id` in Booking debug; injected across Booking/GetOrder/CancelOrder
- **Meal mapping:** RO→`nomeal`, BB→`breakfast`, HB→`halfboard`, FB→`fullboard`
- Java ref: `qaBackend_Enigma/.../serviceAdapters/rhk/RhkAdapter*.java`

---

## API (implemented)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | status, phase |
| POST | `/api/scenarios` | create (202, background) |
| GET | `/api/scenarios` | list |
| GET | `/api/scenarios/{id}` | bundle + status |
| POST | `/api/scenarios/{id}/refresh-booking-ids` | re-inject booking ids |
| DELETE | `/api/scenarios/{id}` | teardown: mocks + contracts + apiKey |
| DELETE | `/api/scenarios/all` | clear all active scenarios |
| GET | `/api/scenarios/{id}/quickwit-logs` | Quickwit search by scenario api_key |
| POST | `/api/logs/quickwit/search` | generic Quickwit search |
| GET | `/api/suppliers` | HBS, EXP, RHK metadata |

### Quickwit (runtime logs)

- Config: `QUICKWIT_LOGS_API_URL` in `backend/.env` (staging: `http://quickwit-nonprod.../api/v1`)
- Index auto-resolve: `hotels-consolelogs-staging-YYYY_MM_DD` (prod: monthly `hotels-consolelogs-prod-apps-YYYY_MM`)
- Client: `app/integrations/quickwit.py` — port of Java `QuickwitLogsActivator`
- CLI: `python scripts/quickwit_search.py "smf-my-namespace" --minutes 60`
- Requires VPN/internal network to reach Quickwit

---

## Code conventions

- Backend package: `backend/app/`
- Pydantic models: `app/models/`
- External HTTP: `app/integrations/` only
- Supplier logic: `app/plugins/`
- Secrets/URLs: `app/config.py` / `backend/.env` — never hardcode

---

## Run locally

```bash
# API
cd backend && PYTHONPATH=. uvicorn app.main:app --reload --port 8000

# UI
cd frontend && npm run dev   # :5173 → proxy :8000
```

---

## Session end (mandatory)

Update `docs/PROGRESS.md`: phase checklist, last session summary, **Next session** prompt, blockers table.

Commit only when user asks.
