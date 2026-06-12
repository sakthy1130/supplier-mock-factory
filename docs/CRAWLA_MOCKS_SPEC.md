# Crawla Mocks — SMF Feature Spec (handoff from Enigma QA planning)

> **Status:** Not started — build in SMF Cursor window only.  
> **Enigma QA automation** (SID creation + verification) is a **separate follow-up** in `qaBackend_Enigma`; do not implement Java tests in this phase unless explicitly requested.

## Purpose

Add a **third SMF UI tab** — **Crawla Mocks** — so manual QA can create supplier mocks aligned to live Crawla prices for Search Merge / Packages Merge testing. SMF ends at **READY scenario + export JSON**. No SID creation, no test execution, no coverage UI.

Parent repo context: `qaBackend_Enigma` Crawla tests (`CreateCrawlaSearchTestData`, `CrawlaSearch_PositiveTest`, `CrawlaSearch_PackageLevel_PositiveTest`) will consume the export JSON in a later phase.

---

## Locked scope for SMF

| SMF log type | Crawla-driven? | Notes |
|--------------|----------------|-------|
| **Search** | **Yes** | Tune EXP/HBS from `minPriceFlexible` anchor |
| **Packages** | **Yes** | Tune EXP/HBS from `hotelPage` anchor (pick one offer row) |
| CancellationPolicy | No | Standard template + linkage |
| PreBooking | No | Linkage from chosen package |
| Booking | No | BookingIdInjector |
| GetOrder | No | Booking id in path |
| CancelOrder | No | Standard |

Full scenario orchestration still runs (mocks + contracts + **new apiKey** per scenario). "Mock only" means **product scope** — not test harness — not "skip apiKey".

---

## Two Crawla staging APIs (backend proxy)

Store API key in `backend/.env` (e.g. `CRAWLA_API_URL`, `CRAWLA_API_KEY`). Never hardcode in frontend.

### 1. Search anchor — `minPriceFlexible`

```
POST http://alm-crawla-realtime-api-stage.alm-data.io/minPriceFlexible
Headers: Content-Type: application/json, apikey: <key>
Body: { atg_hotel_ids[], checkin_date, checkout_date, adult_count:2, room_count:1, kids_count:0, currency:"SAR" }
```

Response: `{ "data": [ { atg_id, min_price, total_amount, room_name, base_amount, tax_amount, currency, ... } ] }`

Use per hotel: **C_search** = `total_amount` (primary), `room_name` for display.

### 2. Package anchor — `hotelPage`

```
POST http://alm-crawla-realtime-api-stage.alm-data.io/hotelPage
(same body shape as minPriceFlexible)
```

Response: `{ "hotels": [ { atg_id, min_price, status, data: [ { room_id, room_name, total_amount, meal, refundability, bed_type, partner_offer, ... } ] } ] }`

UI must let QA **pick one offer row** from `data[]` (default: row matching hotel `min_price`). Use **C_pkg** = selected row `total_amount`, plus `room_id`, `room_name`, `meal`, `refundability`.

**Important:** C_search and C_pkg for the same hotel may differ — tune Search and Packages panels independently.

---

## Six bucket types

| UI label | Internal key | Search: Crawla | Search: EXP | Packages: Crawla | Packages: EXP | HBS |
|----------|--------------|----------------|-------------|------------------|---------------|-----|
| Crawla wins | `CRAWLA_LOWER` | C present | E > C | offers present | E > C_pkg | H > C |
| Expedia wins | `EXPEDIA_LOWER` | C present | E < C | offers present | E < C_pkg | any |
| Equal | `EQUAL` | C present | E ≈ C (±0.05 SAR) | offers present | E ≈ C_pkg | ≈ C |
| Only Expedia | `ONLY_EXPEDIA` | **absent** | INCLUDE | **absent** | INCLUDE | optional |
| Only Crawla | `ONLY_CRAWLA` | C present | **EXCLUDE** | offers present | **EXCLUDE** | INCLUDE (required) |

Optional 7th later: `CRAWLA_PRICE_ZERO` (both sides, crawla total = 0).

### Hotel picker rules

- `CRAWLA_LOWER`, `EXPEDIA_LOWER`, `EQUAL`, `ONLY_CRAWLA` → hotel must appear in **both** Crawla API responses.
- `ONLY_EXPEDIA` → hotel **not** in either Crawla response (manual ATG id or picker of non-anchor hotels).

### EXP mock modes (new backend capability)

- `INCLUDE_HOTEL` — default; mutate prices on template.
- `EXCLUDE_HOTEL` — remove property/hotel from EXP **Search** and **Packages** responses for scenario ATG/supplier id. Required for `ONLY_CRAWLA`.

---

## UI — third tab `crawla` in `App.tsx`

Nav: **Create** | **Browse** | **Crawla Mocks**

### Screen sections

1. **Stay params** — check_in, check_out (checkout = check_in + 2 days helper), SAR fixed display, 1 room / 2 adults / 0 kids.
2. **Hotel list** — textarea or multi-select ATG ids (default: load from config file `data/crawla_hotel_ids.json` or paste list).
3. **Fetch anchors** — buttons:
   - Fetch search anchor (`minPriceFlexible`)
   - Fetch package anchor (`hotelPage`)
   - Show tables with results; filter by selected bucket.
4. **Bucket** — radio: 6 types above.
5. **Hotel select** — dropdown filtered per bucket rules.
6. **Package offer select** — when hotel has `hotelPage.data[]`, table pick one row (show room_id, room_name, total_amount, meal, refundability).
7. **Price panels** — two sections:
   - **Search:** C_search (read-only), E_search (editable, suggested), H_search (editable, suggested)
   - **Packages:** C_pkg + room metadata (read-only), E_pkg (editable), H_pkg (editable)
   - Auto-suggest E/H from bucket formulas on bucket or hotel change.
8. **Namespace** — auto-generate `crawla-{bucket}-{date}-{seq}`.
9. **Create** — `POST` new endpoint (see API below); show `ScenarioProgress` / `ScenarioResult` reuse.
10. **Export** — when READY, show copyable JSON + download button (no test run).

---

## Backend API (new)

### `POST /api/crawla/anchor/search`

Proxy `minPriceFlexible`. Request body: dates + atg_hotel_ids[]. Return normalized list.

### `POST /api/crawla/anchor/packages`

Proxy `hotelPage`. Return normalized `hotels[]` with `data[]` offers.

### `POST /api/crawla/scenarios`

Accept `CrawlaScenarioRequest` (extend or wrap `ScenarioRequest`):

```yaml
namespace, check_in, check_out, atg_hotel_id
bucket: CRAWLA_LOWER | EXPEDIA_LOWER | EQUAL | ONLY_EXPEDIA | ONLY_CRAWLA
search:
  crawla_total: float
  exp_mode: INCLUDE_HOTEL | EXCLUDE_HOTEL
  exp_price: float
  hbs_price: float
packages:
  crawla_room_id: str
  crawla_room_name: str
  crawla_total: float
  meal: str
  refundability: str
  exp_mode: INCLUDE_HOTEL | EXCLUDE_HOTEL
  exp_price: float
  hbs_price: float
suppliers: [ HBS, EXP ]  # both required; packages spec derived from prices above
```

Server:

1. Build `ScenarioRequest` from crawla request (package count=1, prices from panels).
2. Run existing `ScenarioEngine` + orchestrator.
3. Apply **bucket-specific mutations** in `exp.py` / `hbs.py`:
   - `EXCLUDE_HOTEL` strips hotel from Search + Packages EXP templates.
   - Price overrides for INCLUDE modes.
4. Standard contract + apiKey provision.
5. Return `ScenarioBundle` + `crawla_export` block for automation.

### Export JSON (automation handoff)

Written to scenario record or returned in GET bundle:

```json
{
  "bucket": "CRAWLA_LOWER",
  "namespace": "...",
  "api_key": "smf-...",
  "atg_hotel_id": "1057823",
  "check_in": "2026-06-09",
  "check_out": "2026-06-11",
  "search": {
    "crawla_total": 535.91,
    "exp_mode": "INCLUDE_HOTEL",
    "exp_price": 620.0,
    "hbs_price": 650.0
  },
  "packages": {
    "crawla_room_id": "2f981f8a233649d09bd13294025ce34d",
    "crawla_room_name": "Classic Room",
    "crawla_total": 535.91,
    "meal": "RO",
    "refundability": "NO",
    "exp_mode": "INCLUDE_HOTEL",
    "exp_price": 620.0,
    "hbs_price": 650.0
  }
}
```

---

## Suggested price formulas (UI auto-suggest)

| Bucket | E_search / E_pkg | H_search / H_pkg |
|--------|------------------|------------------|
| CRAWLA_LOWER | C × 1.15 | C × 1.25 |
| EXPEDIA_LOWER | C × 0.85 | C × 0.90 |
| EQUAL | C (±0.02) | C |
| ONLY_EXPEDIA | fixed e.g. 500 | optional 600 |
| ONLY_CRAWLA | n/a (EXCLUDE) | C × 1.10 (required) |

---

## Plugin / engine changes

1. **`exp.py`** — `EXCLUDE_HOTEL`: remove matching property from Search + Packages response bodies.
2. **`hbs.py`** — same EXCLUDE not needed for ONLY_CRAWLA (HBS always includes).
3. **`scenario_engine.py`** — accept optional `CrawlaBucketSpec` passed from crawla route; apply after standard package mutation.
4. **Linkage** — chosen package row must propagate to PreBook (existing `propagate_package_linkage`); align `meal` / room name where field maps allow.

---

## Config

Add to `backend/.env.example`:

```
CRAWLA_API_URL=http://alm-crawla-realtime-api-stage.alm-data.io
CRAWLA_API_KEY=
```

---

## Tests (backend)

- `test_crawla_anchor_proxy.py` — mock httpx, normalize responses
- `test_crawla_bucket_exp_exclude.py` — ONLY_CRAWLA removes EXP hotel
- `test_crawla_scenario_request.py` — price suggest + ScenarioRequest mapping
- Extend `test_plugins_p2.py` if EXP exclude logic in plugins

---

## Out of scope (this phase)

- Enigma Java `CrawlaSearch_BucketMatrixTest` / `crawla_bucket_matrix.json`
- Mocking Crawla itself (always live at search time)
- Quickwit / coverage report in SMF UI
- Running Maven or writing `crawla/search.json`

---

## Implementation order

1. Config + `integrations/crawla.py` (httpx client for both endpoints)
2. Routes `api/routes/crawla.py` — anchor proxies
3. `models/crawla_scenario.py` — Pydantic request/export
4. Plugin EXCLUDE_HOTEL support
5. `POST /api/crawla/scenarios` wired to orchestrator
6. Frontend tab + `CrawlaMocksWizard.tsx` component
7. Backend tests
8. Update `docs/PROGRESS.md` when done

---

## Enigma QA reference (read-only, parent repo)

```
qaBackend_Enigma/src/main/java/com/hotels/utils/enigma/core/searchMergeWrapper/
  CrawlaSearchCoverageReportWrapper.java    # bucket classification
  CrawlaSearchValidationWrapper.java        # CRAWLA_SEARCH_001 search level
  CrawlaSearchPackageLevelValidationWrapper.java  # package level
```

Coverage keys: `onlyExpedia`, `onlyCrawla`, `crawlaStrictlyLower`, `expediaStrictlyLower`, `pricesEqual`, `crawlaZeroPrice`.

---

## Resume prompt for SMF agent window

See `docs/CRAWLA_MOCKS_RESUME.md`.
