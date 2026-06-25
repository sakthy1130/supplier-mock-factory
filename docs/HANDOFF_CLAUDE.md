# SMF → Claude handoff (2026-06-25)

Read this after `docs/ARCHITECTURE.md` and `AGENTS.md`. Branch: **`crawla-e2e-package-level`** (ahead of origin by 2 commits; large uncommitted WIP).

---

## Resume prompt (paste into Claude)

```
Resume Supplier Mock Factory (SMF).
Read: docs/HANDOFF_CLAUDE.md, docs/ARCHITECTURE.md, AGENTS.md
Branch: crawla-e2e-package-level
Focus: validate CHC+HBS E2E on staging after re-provision; fix any remaining Crawla currency / contract gaps.
Do not commit unless asked.
```

---

## What this session shipped (uncommitted unless noted)

### Suppliers in scope
| Code | Adapter | Status |
|------|---------|--------|
| HBS | `hotel-connectivity-hbs-adapter` | Stable |
| EXP | `hotels-exp-adapter-service-staging` | Stable |
| RHK | `hotels-rhk-adapter-service-staging` | Wired |
| **CHC** | `hotels-derby-bts-adapter` | **New — needs staging E2E** |

### UI (`ScenarioWizard.tsx`)
- Per-supplier **currency** on supplier tiles (defaults: HBS EUR, EXP/RHK USD, CHC SAR).
- **`room_names`**: hyphen-separated (` - `), one per package; defaults pad like prices when count changes.
- **`refundable`**: comma-separated `true/false` (unchanged parser).

### Backend models
- `PackageSpec.room_names: list[str]` (legacy `room_name` coerced via validator).
- `PackageSpec.supplier_currency: str` (default `SAR`).

### New / changed plugins
| File | Role |
|------|------|
| `backend/app/plugins/chc.py` | CHC Derby BTS mocks: dates, rates, cancel policy, package linkage |
| `backend/app/plugins/supplier_currency.py` | Currency on rate payloads per supplier |
| `backend/app/plugins/room_names.py` | HBS/EXP/RHK room name injection |
| `backend/app/core/chc_paths.py` | CHC contract opt defaults |

### CHC adapter behaviour (critical)

CHC uses **Derby BTS** (`hotel-connectivity-derby-bts-adapter`). Reference repo (read-only): `https://github.com/tajawal/hotel-connectivity-derby-bts-adapter`

**Mock shapes**
- Search: `body.availHotels[].availRoomRates[]`
- Packages / PreBooking: `body.hotelId` + `body.roomRates[]`
- Rate identity: `roomId` + `rateId` (no room display name in mock — adapter resolves name from Redis cache by `roomId` at Search)

**`propagate_package_linkage`** (required): copies Search primary rate `roomId`, `rateId`, `roomCriteria` → Packages + PreBooking. Without this, adapter returns **0 packages**.

**Cancel policy rules (do not regress)**
1. **Contract** must set `isCancellationPolicyOneSlot: true` in `opt` — see `apply_chc_contract_opt_defaults()` in `chc_paths.py`. Forces single `cancellationFee` tier when code is e.g. `4PM1D100P_100P`.
2. **Mock penalties**: keep `cancelDeadline` on single non-noShow penalty; strip no-show penalty.
3. **Refundability codes** (Derby `getRefundability`):
   - `refundable=true` → `cancelPolicy.code = AD0_0`, penalty percent `0`
   - `refundable=false` → `cancelPolicy.code = AD100P_100P`, penalty percent `100`
   - Template code `4PM1D100P_100P` without `AD` prefix is treated as **Refundable** by adapter even at 100% penalty.

**CHC mock paths** (from ingested templates)
- Search: `/api/go/shoppingengine/v4/shopping/multihotels`
- Packages: `/api/go/bookingusb/v4/availability`

### HBS refundability fix (this session)

**Bug:** User set `refundable=false` but HBS adapter showed Refundable.

**Cause:** `mutate_dates()` shifts all `cancellationPolicies.from` to **check-in + 1 day**. Adapter treats future `from` as free-cancel window → refundable despite `rateClass: NRF`.

**Fix:** `_apply_hbs_rate_refundability()` in `hbs.py`:

| User flag | `rateClass` | `rateKey` token | `cancellationPolicies` |
|-----------|-------------|-----------------|------------------------|
| `false` | `NRF` | `~~~NRF~~` | full `amount`, `from: 2000-01-01T00:00:00+00:00` |
| `true` | `REF` | `~~~NOR~~` | `amount: 0`, `from: check-out` |

Search gets same rates via `propagate_package_linkage` (copies Packages rooms → Search).

### Contract provisioner
- CHC clone/minimal contracts call `apply_chc_contract_opt_defaults()`:
  - `isCancellationPolicyOneSlot: true` (forced even if reference has `false`)
  - `availabilityTimeoutSeconds: "30"`
- Ensure `availabilityUrl` is set from Packages mock path (via `mock_urls.py` fallbacks).

### Templates
- `templates/CHC/{Search,Packages,PreBooking,Booking,GetOrder,CancelOrder}/v1.json` — ingested from reference SID
- HBS/EXP templates updated with `ONLY_MATCHING_FIELDS` body matchers (ingest session)
- `field-maps/CHC.json` added

### Tests added / updated
- `backend/tests/test_chc.py` (8 tests)
- `backend/tests/test_chc_paths.py`
- `backend/tests/test_contract_provisioner.py` — CHC `isCancellationPolicyOneSlot`
- `backend/tests/test_plugins_p2.py` — HBS refundability, room names, currency
- Run: `cd backend && PYTHONPATH=. pytest tests/test_chc.py tests/test_chc_paths.py tests/test_plugins_p2.py tests/test_scenario_engine.py -q`

---

## Staging validation sessions (for debugging)

| Session | Issue | Resolution |
|---------|-------|------------|
| `019efe76` | CHC Search `totalResults: 0` | Flat cancel policy missing `cancelDeadline` → NPE in Search transform |
| `019efe7a` | CHC Packages `E9999.1` NPE | Invalid codes `REF`/`NRF` + missing `cancelDeadline` on Packages |
| `019efe9f` | Refundable UI `false` but HBS Refundable | Fixed `_apply_hbs_rate_refundability`; CHC was already non-refundable |

**Important:** After backend changes, user must **delete old scenario and create new one** — MockServer + contracts do not auto-update.

Enigma logs: `https://enigma-logs-staging.almosafer.com/logs/render?file=logs/{sId}/...&domain=Hotels`

Quickwit CLI:
```bash
python3 scripts/quickwit_search.py "{sId}" --index hotels-consolelogs-staging-2026_06_25 --minutes 120
```

Logs API (from backend):
```python
from app.integrations.logs_api import LogsApiClient
# await client.get_log_detail('logs/{sId}/Packages_HBS_....json.gz')
```

---

## Known blockers / not yet fixed

| Item | Notes |
|------|-------|
| **Crawla currency** | Crawla may reject `currency` if not `SAR` while CHC contract has `defaultContractCurrency: AED`. May need contract patch: `defaultContractCurrency` / `affiliateCurrency` → `SAR` for SMF CHC clones. |
| **CHC `availabilityUrl`** | Some sessions showed CHC contract with only `searchUrl` — verify `mock_urls._apply_opt_fallbacks` on clone. |
| **CHC registry placeholders** | `supplier_registry.py` has TODO for real `supplier_id` / `auto_id` — confirm staging values in `.env` `CHC_REFERENCE_CONTRACT_ID`. |
| **`docs/PROGRESS.md`** | Was stale (P8 / 2026-06-10) — update when closing a session. |
| **Uncommitted WIP** | ~38 modified + new CHC files on branch — no commit in this session unless user asks. |

---

## Config checklist (`backend/.env`)

```
CHC_REFERENCE_CONTRACT_ID=...   # clone source for CHC contracts
HBS_REFERENCE_CONTRACT_ID=...
EXP_REFERENCE_CONTRACT_ID=...
RHK_REFERENCE_CONTRACT_ID=663a2b3267e9f7646696be28
MOCK_SERVER_URL=http://mockserver-staging.tajawal.io
LOGS_API_URL=https://enigma-logs-staging.almosafer.com/
QUICKWIT_LOGS_API_URL=...
```

---

## Run locally

```bash
# API
cd backend && source ../.venv/bin/activate
PYTHONPATH=. python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# UI
cd frontend && npm run dev   # :5173 → proxy :8000
```

---

## Next tasks (priority order)

1. **Re-provision test scenario** (HBS + CHC, `refundable=false`, count=1) and confirm adapter `PackagesResponse_*` refundability matches UI.
2. **Crawla E2E** on branch goal — fix currency mismatch if Crawla step still fails.
3. **CHC contract currency** — patch `contract_provisioner` / reference clone if BR requires SAR.
4. **CHC room names** — same `roomId` on all rates ⇒ same cached display name (no mock field); document for QA.
5. **Commit WIP** when user approves — suggest split: (a) CHC supplier, (b) UI package fields, (c) ingest/template matcher changes.
6. Update `AGENTS.md` CHC section with cancel-code + `isCancellationPolicyOneSlot` contract rule (if not already).

---

## Key files quick map

```
backend/app/plugins/chc.py          # CHC mock + cancel + linkage
backend/app/plugins/hbs.py          # HBS refundability (_apply_hbs_rate_refundability)
backend/app/core/chc_paths.py       # isCancellationPolicyOneSlot contract default
backend/app/core/contract_provisioner.py
frontend/src/components/ScenarioWizard.tsx
templates/CHC/
docs/ARCHITECTURE.md
AGENTS.md
```

---

## Architecture rules (unchanged)

- Expectation id: `smf-{namespace}-{supplier}-{logType}` — id-based teardown only
- MockServer priority: 1000
- New apiKey per scenario
- Ingest templates: `ONLY_MATCHING_FIELDS`, strip `header` from request JSON
- Runtime register: path + method only (no body matcher)

---

*Generated 2026-06-25 — Cursor session handoff for Claude Code / Cowork.*
