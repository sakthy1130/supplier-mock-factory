# Automation API — Run Template

Create, run, and (optionally) clean up a supplier-mock scenario from a saved
template in a single call. Built for CI/CD and QA automation: provision mocks,
drive the connectivity core, assert the outcome, tear down.

- **Endpoint:** `POST /api/v1/run-template/{template_id}`
- **Content-Type:** `application/json`
- **Swagger / OpenAPI:** `http://localhost:8000/docs` (schema at `/openapi.json`) —
  auto-generated from the models, always in sync with this doc.
- **Base URL:** `http://localhost:8000` (default; port 8000 per `docker-compose.yml`).

```bash
# Convenience for the curl examples below
export BASE="http://localhost:8000"
export TEMPLATE_ID="b0af7d0d-a108-426f-b908-f611e0e94c8d"
```

> Find a template id via `GET /api/scenario-templates` (returns each template's `id`).

---

## What the run does

1. Load the template by id.
2. Build a scenario (mocks + contracts + apiKey) from the template.
3. Resolve the ATG hotel id to per-supplier hotel ids (mapping service).
4. Drive the core: **search → packages**, and **→ book → poll → getOrder** *only if*
   a package was selected for booking (see `booking_package_index`).
5. Optionally tear everything down (`delete_mock_api_key`).

Two behaviors are **opt-in**, mirroring the UI:

| Behavior | Off by default? | How to turn on |
|---|---|---|
| **Booking flow** | Yes — search + packages only | pass `booking_package_index` |
| **SmartBooking (SB group)** | Inherits the template | pass `sb_enabled` to override |

> **SB routing lives on the template, not the request.** Each supplier's
> `assignment_target` (`apikey` / `sbgroup` / `both`) is saved on the template and
> decides where its contract attaches. The request can only toggle `sb_enabled`
> on/off — it cannot change routing. To get an SB group, the template must have at
> least one supplier targeting `sbgroup` or `both`.

---

## Request fields

All fields are optional (an empty body `{}` is valid and runs search + packages
against **dev**).

| Field | Type | Default | Description |
|---|---|---|---|
| `environment` | string | `"dev"` | Target env: `"dev"` or `"stg"`. **Always set `"stg"` for staging** — the default is dev. |
| `check_in` | string \| null | today | `YYYY-MM-DD`. |
| `check_out` | string \| null | tomorrow | `YYYY-MM-DD`. |
| `hotel_id` | string \| null | template's | Override the ATG hotel id. |
| `booking_package_index` | int ≥ 0 \| null | `null` | Opt into booking. Books the package at this 0-based index (per supplier's list); the first supplier whose list contains it is booked. Omit = search + packages only. |
| `sb_enabled` | bool \| null | `null` | Override the template's SmartBooking. `null` = use template; `true`/`false` = force. |
| `delete_mock_api_key` | bool | `true` | `true` = full cleanup after run. `false` = keep scenario alive for inspection. |
| `assign_api_key_to_br` | bool | `true` | Assign the apiKey to the Static/Dynamic Markup BR rules. |
| `force_cleanup` | bool | `true` | Clean up even if creation/run fails. |
| `timeout_seconds` | int (30–600) | `300` | Max wait for creation + run. |
| `include_logs` | bool | `false` | Include step-by-step execution logs in the response. |

---

## Response fields (selected)

| Field | Description |
|---|---|
| `request_id` | Trace id for this run. |
| `status` | `COMPLETED` \| `FAILED` \| `TIMEOUT`. |
| `scenario_id`, `api_key`, `api_key_id`, `contract_id` | Provisioned scenario identity. |
| `search_id`, `package_id` | Core `sId` / `pId` from the run. |
| `booking_id`, `booking_status`, `order_status`, `booking_match`, `booking_message` | Booking-flow outcome — populated **only when booking ran**. |
| `sb_enabled`, `sb_group_id`, `contract_assignment` | SmartBooking outcome. `contract_assignment` = `{"apikey": [...codes], "sbgroup": [...codes]}` (present when SB is on). |
| `deleted` | `true` if the scenario was torn down. |
| `error` | `{code, message}` on failure. |
| `logs` | Present when `include_logs: true`. |

---

## Scenarios

### 1. Search + packages only (default — no booking, no SB)
```json
{ "environment": "stg" }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg"}'
```

### 2. With booking (book the first package)
Drives search → packages → book → poll → getOrder and verifies the order matches.
```json
{ "environment": "stg", "booking_package_index": 0 }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg","booking_package_index":0}'
```

### 3. SmartBooking inherited from the template
Template already saved with `sb_enabled: true` + supplier routing. Just run it.
```json
{ "environment": "stg" }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg"}'
```

### 4. Force SmartBooking ON (override the template)
Requires the template to have an `sbgroup`/`both` supplier, else returns `FAILED`.
```json
{ "environment": "stg", "sb_enabled": true }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg","sb_enabled":true}'
```

### 5. Force SmartBooking OFF (override the template) — all contracts → apiKey
```json
{ "environment": "stg", "sb_enabled": false }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg","sb_enabled":false}'
```

### 6. Booking + SmartBooking together
```json
{ "environment": "stg", "booking_package_index": 0, "sb_enabled": true }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg","booking_package_index":0,"sb_enabled":true}'
```

### 7. Keep the scenario alive for inspection (skip cleanup) + full logs
```json
{ "environment": "stg", "booking_package_index": 0, "delete_mock_api_key": false, "include_logs": true }
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg","booking_package_index":0,"delete_mock_api_key":false,"include_logs":true}'
```

### 8. Override dates / hotel
```json
{
  "environment": "stg",
  "check_in": "2026-09-10",
  "check_out": "2026-09-14",
  "hotel_id": "1500003",
  "booking_package_index": 0
}
```
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" \
  -d '{"environment":"stg","check_in":"2026-09-10","check_out":"2026-09-14","hotel_id":"1500003","booking_package_index":0}'
```

### 9. Empty body (minimal — runs against **dev**)
```bash
curl -X POST "$BASE/api/v1/run-template/$TEMPLATE_ID" \
  -H "Content-Type: application/json" -d '{}'
```

---

## Sample responses

### Booking + SmartBooking (`COMPLETED`)
```json
{
  "request_id": "req_abc123",
  "status": "COMPLETED",
  "scenario_id": "…",
  "api_key": "…",
  "api_key_id": "…",
  "contract_id": "109837",
  "check_in": "2026-09-10",
  "check_out": "2026-09-14",
  "hotel_id": "1500003",
  "search_id": "019fc799-c6fd-7d53-a032-f22c0c578bff",
  "package_id": "89ffa980-820c-4f86-b17b-c0cc5c0ae7d4",
  "booking_id": "…",
  "booking_status": "CONFIRMED",
  "order_status": "…",
  "booking_match": true,
  "booking_message": null,
  "sb_enabled": true,
  "sb_group_id": "6a8f6eca740731730e3b3377",
  "contract_assignment": { "apikey": ["HBS"], "sbgroup": ["EXT"] },
  "deleted": true,
  "assigned_to_br": true
}
```

### Search + packages only (no booking)
`booking_*` stay `null`; `sb_enabled` is `false` and `contract_assignment` is `null`.

### Failure — SB on with no SB-group supplier
```json
{
  "request_id": "req_def456",
  "status": "FAILED",
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "SmartBooking is enabled but no supplier targets the SB group; set at least one supplier's assignment_target to 'sbgroup' or 'both'."
  }
}
```

---

## Notes & gotchas

- **`environment` defaults to `dev`.** Always pass `"stg"` for staging runs, or you'll
  provision against dev.
- **Booking is opt-in.** No `booking_package_index` → the Booking/GetOrder mocks are
  not created and the run stops at packages (same as the UI with no package picked).
- **`booking_package_index` out of range** for every supplier → booking is skipped and
  `booking_message` explains why (run still succeeds as search + packages).
- **SB routing is a template property.** Save the per-supplier `assignment_target`
  when creating the template; the request only flips `sb_enabled`.
- **Cleanup:** with `delete_mock_api_key: true` (default) the scenario, mocks,
  contracts, and apiKey are removed after the run. Set `false` to inspect them; on
  failure, `force_cleanup: true` still tears down orphaned mocks.
- **Use a real, mapped ATG hotel — not the sample `1010102`.** The supplier hotel
  id is resolved at create time and baked into the mock; if that id isn't mapped in
  the core's **HMS** for the ATG hotel, search returns the hotel but the merge drops
  it (can't key it back to the ATG id) → **no packages, no booking**. The response
  now reports this as `status: "FAILED"`, `error.code: "NO_PACKAGES"`. Verify the
  hotel mapping (e.g. `GET /v2/supplier/HBS/{atg}`) and prefer a hotel known to
  both SMF's mapping service and HMS.
- **`status` reflects the real outcome.** `COMPLETED` means packages were produced
  (and a booking, if requested). A 0-result search returns `FAILED` with
  `NO_PACKAGES`; a booking that yields no `bId` returns `FAILED` with
  `BOOKING_FAILED`. `search_status` / `package_status` show how far the run got.
