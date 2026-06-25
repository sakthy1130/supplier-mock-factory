# SMF Progress — Session Handoff

> **Update this file at the end of every Cursor session.** New agents read this first.

## Current phase

**P9 — Multi-supplier package-level mocks (HBS + EXP + RHK + CHC)** — in progress on branch `crawla-e2e-package-level`

## Last updated

2026-06-25

## Last session summary

### CHC (Choice / Derby BTS) supplier
- New plugin `backend/app/plugins/chc.py`, templates `templates/CHC/`, field map `field-maps/CHC.json`
- Package linkage: Search `roomId`/`rateId`/`roomCriteria` → Packages + PreBooking
- Contract: `apply_chc_contract_opt_defaults()` forces `isCancellationPolicyOneSlot: true` (`chc_paths.py`)
- Cancel policy: single penalty + `cancelDeadline`; codes `AD0_0` / `AD100P_100P` by refundable flag

### HBS refundability fix
- `_apply_hbs_rate_refundability()` — NRF uses immediate cancel `from` (2000-01-01); REF uses `amount: 0` + `from` at check-out
- Fixes adapter showing Refundable when UI `refundable=false` (root cause: `mutate_dates` shifted `from` to check-in+1)

### UI package fields
- Per-supplier currency on wizard tiles
- `room_names` hyphen-separated (` - `), defaults pad with package count
- Prices / refundable comma-separated (unchanged)

### Other
- `supplier_currency.py`, `room_names.py` — HBS/EXP/RHK/CHC wiring
- Ingest: `ONLY_MATCHING_FIELDS` on HBS/EXP templates
- Tests: `test_chc.py`, `test_chc_paths.py`, HBS refundability in `test_plugins_p2.py`

**Full detail:** `docs/HANDOFF_CLAUDE.md`

---

## Phase checklist

| Phase | Description | Status |
|-------|-------------|--------|
| P0–P8 | Bootstrap through Crawla Mocks | ✅ Done |
| P9 | CHC supplier + package-level currency/room names/refundable | 🔄 WIP (uncommitted) |
| P9b | Crawla E2E currency + CHC contract SAR alignment | ⏳ Pending |

---

## Next session — copy into agent prompt

```
Resume Supplier Mock Factory (SMF).
Read: docs/HANDOFF_CLAUDE.md, docs/ARCHITECTURE.md, AGENTS.md
Branch: crawla-e2e-package-level
1. Re-provision HBS+CHC scenario; verify refundable=false on staging Enigma logs
2. Fix Crawla currency / CHC contract defaultContractCurrency if E2E still fails
3. Commit WIP only if user asks
```

---

## Blockers

| Blocker | Owner | Notes |
|---------|-------|-------|
| Stale mocks on MockServer | User | Must delete scenario + recreate after plugin/contract changes |
| Crawla `currency must be SAR` | Dev | CHC contract may clone AED; see HANDOFF |
| CHC_REFERENCE_CONTRACT_ID | User | Must be set in `backend/.env` for contract clone |
| Large uncommitted diff | Dev | ~38 files on `crawla-e2e-package-level` — not committed |

---

## Run locally

```bash
cd backend && source ../.venv/bin/activate
PYTHONPATH=. python -m uvicorn app.main:app --reload --port 8000

cd frontend && npm run dev
```

Open http://localhost:5173

---

## Key file paths

| Path | Purpose |
|------|---------|
| `docs/HANDOFF_CLAUDE.md` | **Claude/Cursor full session handoff** |
| `backend/app/plugins/chc.py` | CHC Derby BTS plugin |
| `backend/app/plugins/hbs.py` | HBS refundability |
| `backend/app/core/chc_paths.py` | CHC contract `isCancellationPolicyOneSlot` |
| `frontend/src/components/ScenarioWizard.tsx` | Package UI fields |
