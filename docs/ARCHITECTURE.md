# Supplier Mock Factory (SMF) — Architecture

## Purpose

Automate supplier mock creation for manual QA: search, packages, cancellation policies, prebooking, booking, getOrder, cancelOrder — then create contracts and a new apiKey per scenario.

## Locked decisions

| Decision | Choice |
|----------|--------|
| Project type | **New repo** — separate from qaBackend_Enigma |
| Stack | **Python 3.12 + FastAPI** backend, **React + Vite + TypeScript** frontend |
| Reference | Port logic from qaBackend_Enigma Java **as reference only** (do not depend on Java jar) |
| Suppliers v1 | **HBS + EXP** |
| Log types v1 | All **7**: Search, Packages, CancellationPolicy, PreBooking, Booking, GetOrder, CancelOrder |
| Mock infra | **Staging MockServer only** — no callback host |
| BookingId | **BookingIdInjector** at scenario create + `refresh_booking_ids` — same id across book/getOrder/cancel |
| apiKey | **New key per scenario** |
| Templates | **Git JSON** on disk (`templates/`, `field-maps/`) — not MongoDB |
| Isolation | **id-based namespace isolation** on every expectation (`smf-{namespace}-{supplier}-{logType}`) with id-based teardown; no request-header matcher |
| Users | Manual QA via web UI |

## High-level flow

```
QA → Scenario Builder UI → POST /api/scenarios
  → ScenarioEngine (mutate templates)
  → LinkageValidator
  → BookingIdInjector
  → MockServer register (id-scoped namespace)
  → Create HBS + EXP contracts (URLs → MockServer)
  → Create new apiKey, attach both contracts, clear cache
  → ScenarioBundle returned
```

## Repository layout

```
supplier-mock-factory/
├── backend/app/
│   ├── api/routes/          # FastAPI endpoints
│   ├── core/                # orchestrator, engine, injector, validator
│   ├── integrations/        # mock_server, backoffice, config_manager, logs_api
│   ├── plugins/             # hbs.py, exp.py
│   ├── ingest/              # template_ingestor, field_map_generator
│   ├── models/              # Pydantic ScenarioRequest, ScenarioBundle
│   └── db/                  # SQLite scenario history
├── frontend/                # React wizard + dashboard
├── templates/{HBS,EXP}/     # MockServer expectation JSON per log type
├── field-maps/              # Per-supplier mutable field paths
└── docs/                    # ARCHITECTURE, PROGRESS, HANDOFF, RESUME
```

## Java reference map (qaBackend_Enigma)

| Python module | Java reference |
|---------------|----------------|
| `integrations/logs_api.py` | `LogS3Wrapper` |
| `integrations/mock_server.py` | `CreateExpectationWrapper`, `DeleteExpectationWrapper`, `AdapterSidLogToMockExpectationUtil` |
| `integrations/backoffice.py` | `ContractsSupplier`, `BackofficeLoginApiActivator` |
| `integrations/config_manager.py` | `UpdateApiKeysConfigWrapper`, `ClearApiKeyCacheActivator` |
| `core/booking_id_injector.py` | `AdapterSidLogToMockExpectationUtil.applyAlignedDerbyResIdsForBookingAndGetOrder` |
| `plugins/hbs.py` | `SupplierRankingHbsJsonUtils` |
| `plugins/exp.py` | `SupplierRankingExtJsonUtils` |

## MockServer expectation shape

- `httpRequest`: path, method, optional JSON body matcher with `ONLY_MATCHING_FIELDS`
- Strip volatile `header` from request body matcher
- `httpResponse`: statusCode, headers, body (supplier payload from `response.body` in logs)
- `priority`: 1000

## ScenarioRequest (DSL)

```yaml
namespace: qa-user-20250605-001
check_in: "2026-08-01"
check_out: "2026-08-03"
hotel_id: "12345"
suppliers:
  - code: HBS
    packages:
      count: 3
      room_basis: RO
      prices: [100, 200, 300]
      refundable: [true, true, false]
  - code: EXP
    packages:
      count: 3
      room_basis: RO
      prices: [100, 200, 300]
      refundable: [true, true, false]
```

## ScenarioBundle (output)

```yaml
namespace: ...
api_key: ...
api_key_id: ...
contracts: { HBS: "...", EXP: "..." }
booking_ids: { HBS: "...", EXP: "..." }
check_in, check_out, hotel_id: ...
mock_server_base_url: ...
expectation_count: 14
status: READY
created_at, expires_at: ...
```

## API endpoints (target)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/scenarios` | Create scenario (async) |
| GET | `/api/scenarios` | List scenarios |
| GET | `/api/scenarios/{id}` | Status + bundle |
| POST | `/api/scenarios/{id}/refresh-booking-ids` | Re-inject booking ids |
| DELETE | `/api/scenarios/{id}` | Teardown |
| POST | `/api/admin/ingest` | Ingest reference SIDs → templates |
| GET | `/api/suppliers` | HBS, EXP metadata |

## Implementation phases

| Phase | Scope | Status |
|-------|-------|--------|
| P0 | Bootstrap, docs, rules, health API, frontend shell | See PROGRESS.md |
| P1 | Template ingest from reference SIDs | Pending |
| P2 | Scenario engine + linkage validator + plugins | Pending |
| P3 | BookingId injector + MockServer register | Pending |
| P4 | Contract + apiKey provisioner + orchestrator | Pending |
| P5 | Full REST API + SQLite persistence | Pending |
| P6 | React UI (wizard, progress, results, list) | Done |
| P7 | Teardown, docker-compose, runbook | Done |
| P8 | Crawla Mocks tab, Crawla anchors, export JSON | Done |

## Environment variables

See `backend/.env.example`.

## Acceptance criteria

1. UI or CLI: HBS+EXP, 3 packages RO 100/200/300 → creates scenario
2. Returns apiKey + 2 contractIds in < 30s (hot path)
3. Booking → getOrder → cancel share same bookingId
4. New scenario → different bookingIds
5. `refresh_booking_ids` works for second booking
6. `teardown` removes scenario expectations on MockServer, and `DELETE /api/scenarios/all` clears every active scenario plus leftover expectations
