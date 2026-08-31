# SMF Requirements Backlog

Requested changes that are **not implemented yet**. One entry per requirement, each with
the current behaviour it changes, the files it touches, and what "done" means — enough to
pick up cold in a later session.

Update the **Status** line when work starts or lands; move nothing out of this file until
it is merged, then mark it `Done` with the commit.

| Status | Meaning |
|---|---|
| `Open` | Agreed, not started |
| `In progress` | Being implemented, branch named in the entry |
| `Blocked` | Waiting on an answer or an external team |
| `Done` | Merged — keep the entry, add the commit |

---

## REQ-001 — Pass the output value for Static and Dynamic BR markup

**Status:** Done — implemented 2026-08-24
**Requested:** 2026-08-24
**Area:** Business Rules provisioning (backend + wizard + Crawla + automation API)

### What it was

Every scenario got the same two markup conditions, from four bare literals in
`business_rules.py` — `10%` static and `15%-25%` dynamic on the apiKey path, repeated on the
contract path. Testing any other markup meant editing source.

### As implemented

Two optional per-scenario values, `static_markup` and `dynamic_markup`. Unset provisions
exactly what it did before.

| Piece | Where |
|---|---|
| `DEFAULT_STATIC_MARKUP` / `DEFAULT_DYNAMIC_MARKUP` + `markup_rules()` — one source both paths iterate | `backend/app/integrations/business_rules.py` |
| `provision(...)` and `provision_for_contracts(...)` take the two values | same file |
| Request fields + normalizing validator + depth gate | `backend/app/models/scenario.py` (`_normalize_markup`, `_validate_provisioning_depth`) |
| Passed at both provision call sites; provisioned values logged in `[br]` | `backend/app/core/orchestrator.py` |
| Automation API | `backend/app/models/run_template.py`, `backend/app/api/routes/run_template.py` |
| Crawla scenarios | `backend/app/models/crawla.py`, `backend/app/api/routes/crawla.py` |
| Wizard inputs for both BR depths (`MarkupFields`, `brWillProvision`) | `frontend/src/components/ScenarioWizard.tsx`, `types/scenario.ts` |
| Crawla inputs (single wizard + per-batch in the queue runner) | `frontend/src/components/CrawlaMocksWizard.tsx`, `CrawlaQueueRunner.tsx`, `types/crawla.ts` |
| Tests | `backend/tests/test_business_rules.py` (wire-level `outputValue`), `test_provisioning_depth.py` (paired-path + normalization), `test_run_template_build.py`, `test_crawla_bucket_exclude.py` |

### Decisions

- **Input format:** static typed bare (`10`), dynamic as a range (`10%-15%`) — but both
  spellings are accepted for both fields and normalized to what BR stores: `10` → `10%`,
  `10-15` → `10%-15%`, `10.0` → `10%`. Reversed ranges, negatives and junk are rejected
  naming the field.
- **Both optional**, defaulting to `10%` / `15%-25%`.
- **Per-template child conditions keep their pinned value.** The child in
  `br_child_conditions.json` (`1%-2%`) exists to give one input a *different* markup from
  its parent, so inheriting would defeat it.
- **`br_contract_conditions.json` overrides also keep their own values** — that file owns
  the whole condition body where an env configures one. Both envs are `{}` today, so the
  branch is dormant; `test_field_map_overrides_keep_their_own_markup` pins it.
- **Depth-gated:** rejected on `contract_only`, which provisions no BR at all. Accepted on
  `full` and `contract_br`. In the wizard the inputs appear only when the scenario will
  actually provision BR (`assign_to_br` or SmartBooking on `full`, always on `contract_br`).

### Also fixed while here

The contract path did not record `output_value` in `setup["rules"]` while the apiKey path
did, so a `contract_br` scenario could not show what markup it provisioned in the UI's
"Business Rule setup" panel. It does now.

### Known limitation

BR answers "already exists" when a condition matching the same rule/parent/input is already
there; the id is reused and deliberately not recorded for teardown
(`_create_contract_condition`). Two scenarios on the same apiKey or contract set with
different markup values may therefore collide — the second keeps the first's value. Confirm
on a staging run before relying on two concurrent scenarios with different markups.

---

## REQ-002 — EXP: total, originalPriceWithVAT and markup

**Status:** Done — implemented 2026-08-24
**Requested:** 2026-08-24 (clarified same day)
**Area:** EXP (Expedia) plugin + wizard package rows

### The ask

Three **optional** fields on an EXP package row — `total`, `originalPriceWithVAT` and
`markup`, all **amounts in supplier currency** — where `total = originalPriceWithVAT +
markup`. SMF builds the EXP mock from them. When the fields are left empty the current flow
runs unchanged, so no existing scenario or template changes behaviour.

### What these names refer to

They are **core packages-response** fields, not EXP payload fields. They live on
`packageRateInfo` / `rooms[].roomRateInfo` in the packages-merge response, alongside
`originalTotal`, `dynamicMarkupFee`, `totalWithoutVAT`, `originalPriceWithoutVAT`,
`finalPriceInSupplierCurrency` and `originalPriceInSupplierCurrency`
(see `hotel-connectivity-packages-merge/src/test/resources/*.json`).

SMF cannot write them directly. It controls only the **supplier-side prices in the EXP
mock**, which reach those fields through the adapter:

```
EXP mock rate prices → adapter → originalPriceWithVAT + markup → packageRateInfo.total
```

**No BR is involved.** EXP runs without business rules — the markup that lands on the
package is the one the **EXP adapter itself derives from the supplier payload**. That is
why this is a mock-content change and not a rules change, and why it does not merge with
[REQ-001](#req-001--pass-the-output-value-for-static-and-dynamic-br-markup).

The three inputs are taken at face value and written into the mock; no FX conversion and
no VAT derivation are performed on them.

### Current behaviour being changed

The wizard collects **one price per package row**
([ScenarioWizard.tsx:42-67](../frontend/src/components/ScenarioWizard.tsx#L42-L67) →
`PackageSpec.prices`), and the EXP plugin writes that single number into **both** money
fields: `_apply_exp_prices()` sets `netPrice` and `totalPrice` to the same value
([exp.py:330-345](../backend/app/plugins/exp.py#L330-L345)), then scales
`occupancy_pricing.totals` and the per-night maps off it. EXP is seeded
`supplier_type: "gross"` ([seed_suppliers.py:181](../backend/app/db/seed_suppliers.py#L181)),
so net and total are exactly the pair that should differ — and today they cannot.

### Touch points

- `backend/app/models/scenario.py` — the three optional fields on `PackageSpec`
  (per-package, like `prices` / `refundable`), defaulting to `None` so absence is
  distinguishable from zero.
- `backend/app/plugins/exp.py` — `_apply_exp_prices`, `_apply_exp_occupancy_pricing`,
  `_fill_price_per_night`, and `_scale_exp_get_order_pricing`
  ([exp.py:264](../backend/app/plugins/exp.py#L264)), which today rescales the whole
  pricing block off one total. The derived branch is additional, not a replacement.
- `frontend/src/components/ScenarioWizard.tsx` + `types/scenario.ts` — the inputs, EXP
  rows only, all three blank by default.
- `backend/tests/test_exp_search_prices.py`, `backend/tests/test_plugins_p2.py` — existing
  EXP price assertions stay as the no-fields-given case.

### Acceptance criteria

- An EXP scenario giving the three values produces a mock whose rate prices,
  `occupancy_pricing.totals` and per-night maps are consistent with them, and the package
  core returns carries the requested `originalPriceWithVAT`, `markup` and `total`.
- `originalPriceWithVAT` + `markup` ≠ `total` is **rejected at scenario creation** with a
  message naming the three values and the expected total — never silently corrected.
- A partial set (one or two of the three) is rejected with the same clarity.
- Giving none of the three produces byte-identical mocks to today.
- GetOrder pricing stays consistent with the booked package either way.

### Decisions (2026-08-24)

- **Markup format:** an **amount** in supplier currency — `120` means 120 SAR. Not a
  percentage, not a range; no `%` in the UI, the payload or the model.
- **Validation:** the total the QA enters must equal `originalPriceWithVAT + markup`.
  Enforced **only on EXP mock creation**, and rejected rather than back-solved.
- **FX / VAT:** out of scope. The mock is built from the three values as given; SMF
  performs no currency conversion and derives no VAT.
- **Whose markup:** the EXP adapter's own. EXP runs with **no BR applied**, so this never
  touches the markup rules and does not merge with
  [REQ-001](#req-001--pass-the-output-value-for-static-and-dynamic-br-markup).

### Verified: which EXP fields the adapter reads

From `tajawal/hotel-connectivity-exp-adapter` — `getRoomRateInfo()` in
`src/helper/util.js`, fed by `hotel-search.transformer.js` and
`room-availability.transformer.js`, which read the same three nodes:

| Core field | Adapter expression | EXP payload source |
|---|---|---|
| `total` / `originalTotal` | `FX(basePrice)` | `occupancy_pricing[occ].totals.inclusive.request_currency.value` |
| `markup.dynamic` | `FX(marketingFee)` | `occupancy_pricing[occ].totals.marketing_fee.request_currency.value` |
| `markup.static` | always `null` | — (confirms no BR on EXP) |
| `finalTax` / `originalTax` | `FX(totalTax)` | `totals.inclusive − totals.exclusive` |
| `originalPriceInSupplierCurrency` | `basePrice` | `totals.inclusive` (billable currency for the supplier-currency figure) |

The search transformer also sets `netPrice = price − marketingFees`, so **the markup sits
inside the inclusive total** rather than on top of it: net = inclusive − marketing_fee.

**It is `marketing_fee`, not `gross_profit`** — `gross_profit` appears nowhere in the
adapter. So the mock must write:

```
totals.inclusive     = total     (both request_currency and billable_currency)
totals.marketing_fee = markup    (equals total − originalPriceWithVAT by validation)
totals.exclusive     = total − tax, tax proportion preserved from the template
```

Before this, `_apply_exp_prices` scaled the whole `totals` block off one number, so
`marketing_fee` moved proportionally and the markup was whatever ratio the captured template
happened to have — and Search and Packages, captured from different SIDs, disagreed with
each other (107.78 vs 117.11 on a 1120 package). These fields make it explicit and
consistent.

### As implemented (2026-08-24)

| Piece | Where |
|---|---|
| `total` / `original_price_with_vat` / `markup` + the add-up validator | `backend/app/models/scenario.py` (`PackageSpec`, `has_explicit_pricing`) |
| Writing the totals block | `backend/app/plugins/exp.py` (`_set_exp_total_and_markup`, called from `_apply_exp_occupancy_pricing` only when a markup is passed) |
| GetOrder follows the explicit total | `backend/app/plugins/exp.py` (`_link_booking_flow` via `_normalized_totals`) |
| Saved templates + automation API | `backend/app/models/scenario_template.py`, `backend/app/api/routes/run_template.py` |
| EXP-only wizard columns | `frontend/src/components/ScenarioWizard.tsx` (`EXPLICIT_PRICING_SUPPLIERS`), `.package-row-explicit` in `frontend/src/App.css` |
| Template paste-JSON import | `frontend/src/utils/templateImport.ts` |
| Tests | `backend/tests/test_exp_search_prices.py` (explicit-pricing + validation sections) |

### Found while implementing — not fixed

- **EXP PreBooking is not priced by the scenario at all.** Its body is a bare rate, so
  `_exp_property_entries` finds nothing to walk and no price is applied: the mock replays the
  template's captured price (526.75 on the current template) whatever the scenario asked
  for. True before and after this change. `test_prebooking_pricing_is_untouched_by_the_scenario`
  pins the current behaviour so the gap is visible; fixing it changes what every existing EXP
  scenario returns from price-check, so it needs its own decision.
- **Downstream `total` may not equal `originalPriceWithVAT + markup`.** In packages-merge
  `MarkupOnPackageResponse` (~line 304), for a **Gross** supplier — which EXP is —
  `markup.dynamic` is added to `netPrice`, while
  `originalPriceWithVAT = roomRateInfo.getTotal()` and
  `total = originalPriceWithVAT + commission + VAT`. A package-level
  `Common.overridePackageRateInfo()` in a dependency jar adjusts these further. So the
  identity is enforced where it was asked for — at mock creation — but the packages response
  may still show `total == originalPriceWithVAT` when commission and VAT are zero. Confirm on
  the first staging run.
- **Multi-occupancy.** `occupancy_pricing` can hold several occupancy keys, and each is given
  the same total (the pre-existing behaviour of `_apply_exp_occupancy_pricing`). Whether a
  multi-room total should be split across occupancies is undecided.
- EXP only for now. Extending to other gross suppliers is a matter of adding their code to
  `EXPLICIT_PRICING_SUPPLIERS` and checking their adapter reads an equivalent markup node.

---

## Related, already implemented

Context worth knowing before starting either item above:

- BR provisioning depths and what each one creates — `docs/AUTOMATION_API.md`.
- Per-template child BR conditions under DynamicMarkup —
  `field-maps/br_child_conditions.json`, consumed at
  [business_rules.py:249](../backend/app/integrations/business_rules.py#L249).
- EXP contract opt defaults and the gross/net handling — `backend/app/core/exp_paths.py`.
