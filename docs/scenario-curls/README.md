# Scenario curl examples

One paste-ready `curl` per `POST /api/scenarios` scenario — nothing but the command, so it
drops straight into a terminal or Postman's *Import → Raw text*. Files `18`–`21` are negative
cases that should return **422** and provision nothing.

Before running one:

- **Change `namespace`.** It must be unique — a repeat is a **409**. Each file ships a distinct
  `qa-20260819-sNN` so the whole set can be run back to back, but re-running a file needs a
  fresh value.
- **`X-SMF-Env`** picks the target environment (`stg` or `dev`). It decides which Backoffice,
  MockServer and database the scenario lands in.
- Files `02` and `04` contain `REPLACE_WITH_YOUR_APIKEY` — set it to an apiKey you own.
- Check-in/out are `2026-09-01`/`2026-09-03`; move them if they've gone past.

The response is **202 with `status: PENDING`** — provisioning runs in the background. Poll
until the status is terminal, then tear down:

```bash
curl --location 'http://localhost:8000/api/scenarios/<id>' --header 'X-SMF-Env: stg'
curl --location --request DELETE 'http://localhost:8000/api/scenarios/<id>' --header 'X-SMF-Env: stg'
```

## Provisioning depth — the seven shapes

| File | Creates | Tests |
|---|---|---|
| `01-contract-only-no-apikey` | mocks + contract | the contract body/opt URLs alone |
| `02-contract-only-existing-apikey` | + attached to your key | searching with a key you already trust |
| `03-contract-br-no-apikey` | + contract → BR | markup driven by contract, not apiKey |
| `04-contract-br-existing-apikey` | + attached to your key | contract-scoped markup, searchable now |
| `05-full-br-off` | mocks + contract + new apiKey | clean pricing baseline, no markup |
| `06-full-br-on` | + apiKey → BR (10%, 15–25%) | the default; the comparison point |
| `07-full-smartbooking` | + SB group and config | SB matching / upgrade / profitable-SB |

## Supplier composition

| File | Shape |
|---|---|
| `08-single-supplier` | one supplier — isolates one adapter |
| `09-multi-supplier-merge` | HBS + EXP + CHC + EXT — merge, market price, cheapest-wins |
| `10-same-supplier-twice` | EXP twice → contracts `EXP` and `EXP-2` |

## Package matrix and booking

| File | Shape |
|---|---|
| `11-refundable-and-nonrefundable` | the refundability pair in one response |
| `12-board-basis-mix` | RO / BB / HB |
| `13-search-only-no-booking` | no booking mocks at all (fastest) |
| `14-multi-supplier-each-books` | both suppliers book their own package |

## Supplier mutations

| File | Shape |
|---|---|
| `15-mutation-search-price-drift` | price differs between Search and Packages |
| `16-mutation-room-name-drift` | room name differs between Search and Packages |
| `17-mutation-exclude-hotel` | one supplier drops the hotel (ONLY_CRAWLA shape) |

## Rejected combinations (expect 422, nothing provisioned)

| File | Why it fails |
|---|---|
| `18-rejected-smartbooking-with-contract-depth` | SB needs a new apiKey → requires `full` |
| `19-rejected-existing-apikey-with-full` | `full` creates its own apiKey |
| `20-rejected-crawla-with-contract-depth` | Crawla drives BR off the apiKey → requires `full` |
| `21-rejected-smartbooking-without-sbgroup-target` | the SB group would be created empty |

## Three things the Swagger example gets wrong

Worth reading before copying a payload out of Swagger, which fills in every optional field:

1. **`sb_config` activates SmartBooking on its own** — presence, not the `sb_enabled` flag. The
   generated example ships a populated `sb_config` with every `assignment_target` left at
   `apikey`, so it *is* an SB scenario and it 422s (that's file `21`). Delete `sb_config`
   entirely for a non-SB scenario.
2. **`instance` is server-assigned** from list position. Sending it does nothing: two entries
   of one code become `EXP` and `EXP-2` regardless.
3. **`supplier_hotel_ids` is ignored.** The create route resolves it from `atg_hotel_id` via the
   mapping service and overwrites whatever you send
   ([hotel_mapping_service.py:20-22](../../backend/app/services/hotel_mapping_service.py#L20-L22)),
   which is why these examples omit it. To preview the mapping first:
   `curl --location 'http://localhost:8000/api/hotels/mapping?atg_hotel_id=1446194&suppliers=HBS,EXP'`

## Keeping these honest

Every payload here has been parsed out of its `--data` block and run through the real
`ScenarioRequest` model: positives must be accepted, negatives rejected with the expected
message. Re-check after changing the model:

```bash
cd backend && python3 - <<'PY'
import json
from pathlib import Path
from pydantic import ValidationError
from app.models.scenario import ScenarioRequest
for path in sorted(Path("../docs/scenario-curls").glob("*.txt")):
    payload = json.loads(path.read_text().split("--data '", 1)[1].rsplit("'", 1)[0])
    expect_reject = path.name.startswith(("18", "19", "20", "21"))
    try:
        ScenarioRequest(**payload)
        print(("FAIL " if expect_reject else "ok   ") + path.name)
    except ValidationError as exc:
        print(("ok   " if expect_reject else "FAIL ") + path.name, exc.errors()[0]["msg"][:70])
PY
```
