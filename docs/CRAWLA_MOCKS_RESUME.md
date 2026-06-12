# Resume — Crawla Mocks feature (SMF)

Paste the block below into a **new Agent chat** in the **supplier-mock-factory** Cursor window.

---

```
Build SMF "Crawla Mocks" feature — new third UI tab.

Read first (in order):
1. supplier-mock-factory/docs/CRAWLA_MOCKS_SPEC.md   ← full spec (source of truth)
2. supplier-mock-factory/docs/ARCHITECTURE.md
3. supplier-mock-factory/docs/PROGRESS.md
4. supplier-mock-factory/.cursor/rules/smf.mdc
5. supplier-mock-factory/AGENTS.md

Goal:
- Third tab "Crawla Mocks" in frontend (alongside Create + Browse)
- Backend: proxy two Crawla APIs (minPriceFlexible + hotelPage), POST /api/crawla/scenarios
- Six buckets: CRAWLA_LOWER, EXPEDIA_LOWER, EQUAL, ONLY_EXPEDIA, ONLY_CRAWLA (+ optional CRAWLA_PRICE_ZERO later)
- Crawla drives SMF Search + Packages mocks only; PreBook/Booking/GetOrder/Cancel stay standard SMF
- EXP EXCLUDE_HOTEL mode for ONLY_CRAWLA (no Expedia search or package for chosen ATG hotel)
- ONLY_EXPEDIA: hotel not in Crawla anchors; EXP includes hotel
- Export JSON (api_key, bucket, search + packages panels) for Enigma automation — do NOT build Java tests in this phase

Stack locked: Python 3.12 FastAPI + React Vite TS. No Java.

Follow implementation order in CRAWLA_MOCKS_SPEC.md.
Update docs/PROGRESS.md when finished (phase, summary, next session, blockers).
Commit only if user asks.
```

---

## Verify workspace

- Root should be `supplier-mock-factory/` OR monorepo with that folder open
- Backend: `cd backend && PYTHONPATH=. uvicorn app.main:app --reload --port 8000`
- Frontend: `cd frontend && npm run dev`

## After SMF is done (separate Enigma window)

```
Resume Crawla bucket matrix automation in qaBackend_Enigma.
Read: supplier-mock-factory/docs/CRAWLA_MOCKS_SPEC.md (export JSON section)
Read: .cursor/skills/search-merge/SKILL.md
Build: crawla/crawla_bucket_matrix.json consumer + CrawlaSearch_BucketMatrixTest
Use SMF export JSON as test input; SMF already created mocks.
```
