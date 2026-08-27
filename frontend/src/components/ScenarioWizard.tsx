import { useEffect, useMemo, useState } from 'react'
import { resolveHotelMapping } from '../api/hotels'
import { getActiveEnv, type SmfEnv } from '../api/base'
import { PROVISIONING_DEPTHS, PREBOOKING_STATUSES } from '../types/scenario'
import type {
  AssignmentTarget,
  ProvisioningDepth,
  PreBookingStatus,
  ScenarioRequest,
  SupplierCode,
} from '../types/scenario'
import { DEFAULT_ROOM_BASIS, DEFAULT_ROOM_NAME, DEFAULT_SUPPLIER_CURRENCIES } from '../types/scenario'
import type { SupplierListItem } from '../api/client'

function defaultNamespace() {
  const d = new Date()
  const stamp = d.toISOString().slice(0, 10).replace(/-/g, '')
  const suffix = Math.random().toString(36).slice(2, 6)
  return `qa-${stamp}-${suffix}`
}

export interface PackageRow {
  roomBasis: string
  roomName: string
  price: string
  refundable: boolean
  /**
   * EXP only, both or neither: the split of `price` into pre-markup + markup, in supplier
   * currency, where price = originalPriceWithVat + markup. `price` is the gross total, so
   * there is no separate total field. Blank means the existing flow — the mock's markup
   * rides whatever ratio the captured template had. See docs/REQUIREMENTS.md REQ-002.
   */
  originalPriceWithVat?: string
  markup?: string
}

const DEFAULT_ROW_PRICES = [100, 200, 300]

function defaultPackageRow(index: number): PackageRow {
  return {
    roomBasis: DEFAULT_ROOM_BASIS,
    roomName: DEFAULT_ROOM_NAME,
    price: String(DEFAULT_ROW_PRICES[index] ?? DEFAULT_ROW_PRICES[DEFAULT_ROW_PRICES.length - 1]),
    refundable: true,
    // Blank on purpose: an EXP scenario only opts into explicit pricing when filled in.
    originalPriceWithVat: '',
    markup: '',
  }
}

/** The two BR markup output values, shown wherever this scenario will provision BR.
 *
 *  Sent as typed: the backend normalizes `10` → `10%` and `10-15` → `10%-15%`, so a QA can
 *  use either spelling. Blank means the BR defaults (10% static, 15%-25% dynamic).
 */
function MarkupFields({
  staticMarkup,
  dynamicMarkup,
  onStatic,
  onDynamic,
  showDynamic = true,
}: {
  staticMarkup: string
  dynamicMarkup: string
  onStatic: (value: string) => void
  onDynamic: (value: string) => void
  showDynamic?: boolean
}) {
  return (
    <div className="depth-field" style={{ marginTop: '0.75rem' }}>
      <label htmlFor="static-markup">Static markup (optional)</label>
      <input
        id="static-markup"
        value={staticMarkup}
        onChange={(e) => onStatic(e.target.value)}
        placeholder="10"
        spellCheck={false}
        autoComplete="off"
      />
      {showDynamic && (
        <>
          <label htmlFor="dynamic-markup" style={{ marginTop: '0.5rem' }}>
            Dynamic markup (optional)
          </label>
          <input
            id="dynamic-markup"
            value={dynamicMarkup}
            onChange={(e) => onDynamic(e.target.value)}
            placeholder="10%-15%"
            spellCheck={false}
            autoComplete="off"
          />
        </>
      )}
      <p className="hint">
        {showDynamic ? (
          <>
            Output values for Room Static Markup In Percentage (3) and Room Dynamic Markup In
            Percentage (4). Leave blank for the defaults, 10% and 15%-25%. A plain number is read
            as a percentage, so <code>10</code> and <code>10%</code> both work, as do{' '}
            <code>10-15</code> and <code>10%-15%</code>.
          </>
        ) : (
          <>
            Output value for Room Static Markup In Percentage (3). This environment has no
            DynamicMarkup rule, so static is all there is. Leave blank for the default, 10%. A
            plain number is read as a percentage, so <code>10</code> and <code>10%</code> both
            work.
          </>
        )}
      </p>
    </div>
  )
}

/** Suppliers whose payload carries its own markup, so the price-split fields are shown.
 *  EXP runs with no business rules — its markup comes from the response — so it is the
 *  only supplier where setting these means anything. */
const EXPLICIT_PRICING_SUPPLIERS: SupplierCode[] = ['EXP']

/** Envs that price EXP NET. The split only exists for a GROSS supplier, where the markup
 *  sits inside totals.inclusive; a net contract has no such node, so the fields are
 *  hidden here and the backend rejects them (see scenario_engine). */
const NET_EXP_ENVS: SmfEnv[] = ['odis']

/** Envs with no DynamicMarkup rule — Static Markup (rule 3) is all there is.
 *  Mirrors STATIC_ONLY_ENVS in backend/app/integrations/business_rules.py. */
const STATIC_ONLY_ENVS: SmfEnv[] = ['odis']

/** Envs with no SmartBooking. Mirrors SB_UNSUPPORTED_ENVS in the backend. */
const NO_SMART_BOOKING_ENVS: SmfEnv[] = ['odis']

function hasDynamicMarkup(env: SmfEnv): boolean {
  return !STATIC_ONLY_ENVS.includes(env)
}

function hasSmartBooking(env: SmfEnv): boolean {
  return !NO_SMART_BOOKING_ENVS.includes(env)
}

function showExplicitPricing(code: SupplierCode, env: SmfEnv): boolean {
  if (code === 'EXP' && NET_EXP_ENVS.includes(env)) return false
  return EXPLICIT_PRICING_SUPPLIERS.includes(code)
}

function defaultPackageRows(count: number): PackageRow[] {
  return Array.from({ length: count }, (_, index) => defaultPackageRow(index))
}

interface ParsedRows {
  room_basis: string[]
  room_names: string[]
  prices: number[]
  refundable: boolean[]
  original_price_with_vat?: number[]
  markup?: number[]
}

/** Parse one explicit-pricing cell, or null when the field was left blank. */
function parseOptionalAmount(
  supplierLabel: string,
  index: number,
  label: string,
  raw: string | undefined,
): number | null {
  const text = (raw ?? '').trim()
  if (!text) return null
  const value = Number(text)
  if (Number.isNaN(value)) {
    throw new Error(`${supplierLabel} package ${index + 1}: ${label} must be a number`)
  }
  if (value < 0) {
    throw new Error(`${supplierLabel} package ${index + 1}: ${label} must not be negative`)
  }
  return value
}

function parseRows(supplierLabel: string, rows: PackageRow[]): ParsedRows {
  const room_basis: string[] = []
  const room_names: string[] = []
  const prices: number[] = []
  const refundable: boolean[] = []
  const original_price_with_vat: number[] = []
  const markup: number[] = []
  let explicitRows = 0
  rows.forEach((row, index) => {
    const basis = row.roomBasis.trim().toUpperCase() || DEFAULT_ROOM_BASIS
    const name = row.roomName.trim() || DEFAULT_ROOM_NAME
    const price = Number(row.price)
    if (Number.isNaN(price)) {
      throw new Error(`${supplierLabel} package ${index + 1}: price must be a number`)
    }
    room_basis.push(basis)
    room_names.push(name)
    prices.push(price)
    refundable.push(row.refundable)

    const rowOriginal = parseOptionalAmount(
      supplierLabel, index, 'original price with VAT', row.originalPriceWithVat,
    )
    const rowMarkup = parseOptionalAmount(supplierLabel, index, 'markup', row.markup)
    const filled = [rowOriginal, rowMarkup].filter((value) => value !== null).length
    if (filled === 0) return
    if (filled < 2) {
      throw new Error(
        `${supplierLabel} package ${index + 1}: fill original price with VAT and markup ` +
          'together, or leave both blank',
      )
    }
    // The price IS the gross total, so the split has to reconcile with it. Caught here so
    // the message points at the row, but the backend re-checks — the automation API and
    // saved templates reach the same validator.
    if (Math.abs(price - (rowOriginal! + rowMarkup!)) >= 0.01) {
      throw new Error(
        `${supplierLabel} package ${index + 1}: price ${price} must equal ` +
          `original price with VAT ${rowOriginal} + markup ${rowMarkup} ` +
          `(= ${Number((rowOriginal! + rowMarkup!).toFixed(2))})`,
      )
    }
    explicitRows += 1
    original_price_with_vat.push(rowOriginal!)
    markup.push(rowMarkup!)
  })

  // All rows or none: a partial list would price only some packages explicitly, which the
  // backend rejects for the same reason.
  if (explicitRows > 0 && explicitRows !== rows.length) {
    throw new Error(
      `${supplierLabel}: fill original price with VAT and markup on every package or on none`,
    )
  }

  const parsed: ParsedRows = { room_basis, room_names, prices, refundable }
  if (explicitRows > 0) {
    parsed.original_price_with_vat = original_price_with_vat
    parsed.markup = markup
  }
  return parsed
}

/** How many suppliers start ticked when the wizard opens with no template. */
const DEFAULT_ENABLED_COUNT = 2

export interface ScenarioWizardTemplate {
  atgHotelId?: string
  enabledSuppliers?: Partial<Record<SupplierCode, boolean>>
  // Either one row set per supplier (older callers) or a LIST of row sets — one per
  // supplier instance, for templates that carry the same supplier twice.
  packages?: Partial<Record<SupplierCode, PackageRow[] | PackageRow[][]>>
  supplierCurrencies?: Partial<Record<SupplierCode, string>>
  contractCurrencies?: Partial<Record<SupplierCode, string>>
  sbEnabled?: boolean
  assignmentTargets?: Partial<Record<SupplierCode, AssignmentTarget>>
  prebookingStatuses?: Partial<Record<SupplierCode, PreBookingStatus>>
  prebookingChangedPrices?: Partial<Record<SupplierCode, string>>
  canPrebook?: Partial<Record<SupplierCode, boolean | undefined>>
  bookingRows?: Partial<Record<SupplierCode, (number | null)[]>>
  /** Template mode only: what the template is called and which tab it lives on. */
  templateLabel?: string
  templateDescription?: string
  templateKind?: 'templateBeddingMock' | 'preBookingMock'
}

/** Accept a flat row set or a list of them, always yielding one entry per instance. */
function templateInstances(
  packages: PackageRow[] | PackageRow[][] | undefined,
  fallback: () => PackageRow[],
): PackageRow[][] {
  if (!packages || packages.length === 0) return [fallback()]
  return Array.isArray(packages[0]) ? (packages as PackageRow[][]) : [packages as PackageRow[]]
}

interface Props {
  onSubmit: (request: ScenarioRequest, meta?: TemplateMeta) => Promise<void>
  busy: boolean
  initialTemplate?: ScenarioWizardTemplate
  /** Configured suppliers for the active env — from GET /api/suppliers. */
  availableSuppliers: SupplierListItem[]
  /**
   * 'scenario' (default) provisions. 'template' saves the same composition as a
   * template instead — same fields, same rows, so the two can never describe
   * different things. Namespace and dates are hidden: they belong to a run.
   */
  mode?: 'scenario' | 'template'
  onCancel?: () => void
}

export interface TemplateMeta {
  label: string
  description: string
  kind: 'templateBeddingMock' | 'preBookingMock'
}

export function ScenarioWizard({
  onSubmit,
  busy,
  initialTemplate,
  availableSuppliers,
  mode = 'scenario',
  onCancel,
}: Props) {
  const isTemplate = mode === 'template'
  // App remounts the wizard on env change (it unmounts whenever tab !== 'create'), so
  // reading this once per render is enough — no subscription needed.
  const activeEnv = getActiveEnv()
  const supplierCodes = useMemo(
    () => availableSuppliers.map((s) => s.code),
    [availableSuppliers],
  )
  const [namespace, setNamespace] = useState(defaultNamespace)
  const [checkIn, setCheckIn] = useState('2026-09-01')
  const [checkOut, setCheckOut] = useState('2026-09-03')
  const [atgHotelId, setAtgHotelId] = useState(() => initialTemplate?.atgHotelId ?? '1446194')
  const [supplierHotelIds, setSupplierHotelIds] = useState<Record<string, string>>({})
  const [mappingHint, setMappingHint] = useState<string | null>(null)
  const [mappingLoading, setMappingLoading] = useState(false)
  // One entry per configured supplier, seeded from the API's defaults and then
  // overlaid with whatever the template (if any) specified.
  const [supplierCurrencies, setSupplierCurrencies] = useState<Record<SupplierCode, string>>(() =>
    Object.fromEntries(
      availableSuppliers.map((s) => [
        s.code,
        initialTemplate?.supplierCurrencies?.[s.code] ?? s.default_supplier_currency,
      ]),
    ),
  )
  const [contractCurrencies, setContractCurrencies] = useState<Record<SupplierCode, string>>(() =>
    Object.fromEntries(
      availableSuppliers.map((s) => [
        s.code,
        initialTemplate?.contractCurrencies?.[s.code] ?? s.default_contract_currency,
      ]),
    ),
  )
  // One entry per supplier INSTANCE: a supplier can be added more than once (two
  // EXP contracts at different prices in one scenario), so each code holds a list
  // of package-row sets rather than a single set. Templates carry one set, which
  // becomes instance 1.
  const [supplierPackages, setSupplierPackages] = useState<Record<SupplierCode, PackageRow[][]>>(() =>
    Object.fromEntries(
      availableSuppliers.map((s) => [
        s.code,
        templateInstances(initialTemplate?.packages?.[s.code], () => defaultPackageRows(3)),
      ]),
    ),
  )
  const [enabledSuppliers, setEnabledSuppliers] = useState<Record<SupplierCode, boolean>>(() =>
    Object.fromEntries(
      availableSuppliers.map((s, index) => [
        s.code,
        initialTemplate?.enabledSuppliers?.[s.code] ?? index < DEFAULT_ENABLED_COUNT,
      ]),
    ),
  )
  // Which package row the Booking/GetOrder flow is built for, per supplier instance.
  // null = no booking flow (only search + package mocks created).
  // One slot per supplier instance — must stay the same length as supplierPackages,
  // or toggling the Book radio on a template-loaded second instance would no-op.
  const [bookingRow, setBookingRow] = useState<Record<SupplierCode, (number | null)[]>>(() =>
    Object.fromEntries(
      availableSuppliers.map((s) => [
        s.code,
        initialTemplate?.bookingRows?.[s.code] ??
          templateInstances(initialTemplate?.packages?.[s.code], () => []).map(() => null),
      ]),
    ),
  )
  const [assignToBr, setAssignToBr] = useState(true)
  // BR markup output values. Blank = the backend defaults (10% / 15%-25%).
  const [staticMarkup, setStaticMarkup] = useState('')
  const [dynamicMarkup, setDynamicMarkup] = useState('')
  // How far provisioning goes. 'full' keeps the historical behaviour.
  const [depth, setDepth] = useState<ProvisioningDepth>('full')
  const [existingApiKey, setExistingApiKey] = useState('')
  // SmartBooking: create the apiKey with SB enabled, and per-supplier route each
  // contract to the apiKey, the SB group, or both (default apikey).
  // Per supplier, like assignmentTargets: one supplier can be sold out while another
  // stays available, which is how a multi-supplier partial case is composed today.
  const [prebookingStatus, setPrebookingStatus] = useState<Record<string, PreBookingStatus>>(
    () => ({ ...(initialTemplate?.prebookingStatuses ?? {}) }) as Record<string, PreBookingStatus>,
  )
  const [prebookingChangedPrice, setPrebookingChangedPrice] = useState<Record<string, string>>(
    () => ({ ...(initialTemplate?.prebookingChangedPrices ?? {}) }) as Record<string, string>,
  )
  // undefined = leave the reference contract alone (the default).
  const [canPrebook, setCanPrebook] = useState<Record<string, boolean | undefined>>(
    () => ({ ...(initialTemplate?.canPrebook ?? {}) }) as Record<string, boolean | undefined>,
  )
  const [templateLabel, setTemplateLabel] = useState(() => initialTemplate?.templateLabel ?? '')
  const [templateDescription, setTemplateDescription] = useState(
    () => initialTemplate?.templateDescription ?? '',
  )
  const [templateKind, setTemplateKind] = useState<'templateBeddingMock' | 'preBookingMock'>(
    () => initialTemplate?.templateKind ?? 'templateBeddingMock',
  )
  const [sbEnabled, setSbEnabled] = useState(() => initialTemplate?.sbEnabled ?? false)
  // A template saved on stg can carry sbEnabled=true into an env with no SmartBooking,
  // where the checkbox is hidden. Everything behavioural reads this, not the raw state,
  // so such a template runs with SB off instead of asking for a group that cannot exist.
  const sbActive = sbEnabled && hasSmartBooking(activeEnv)
  const [assignmentTargets, setAssignmentTargets] = useState<Record<SupplierCode, AssignmentTarget>>(() =>
    Object.fromEntries(
      availableSuppliers.map((s) => [s.code, initialTemplate?.assignmentTargets?.[s.code] ?? 'apikey']),
    ),
  )
  const [formError, setFormError] = useState<string | null>(null)

  const suppliers = useMemo(
    () => supplierCodes.filter((code) => enabledSuppliers[code]),
    [enabledSuppliers, supplierCodes],
  )

  // Flattened supplier entries in submit order. `label` mirrors the instance key the
  // backend derives ("EXP", then "EXP-2"), so the summary line names what will
  // actually be created.
  const supplierEntries = useMemo(
    () =>
      suppliers.flatMap((code) =>
        supplierPackages[code].map((_rows, instance) => ({
          code,
          instance,
          label: instance === 0 ? code : `${code}-${instance + 1}`,
        })),
      ),
    [suppliers, supplierPackages],
  )
  const supplierEntryLabels = useMemo(
    () => supplierEntries.map((entry) => entry.label),
    [supplierEntries],
  )

  useEffect(() => {
    const atg = atgHotelId.trim()
    if (!atg || suppliers.length === 0) {
      setSupplierHotelIds({})
      setMappingHint(null)
      return
    }

    let cancelled = false
    setMappingLoading(true)
    setMappingHint(null)

    const timer = window.setTimeout(() => {
      resolveHotelMapping(atg, suppliers)
        .then((result) => {
          if (cancelled) return
          setSupplierHotelIds(result.supplier_hotel_ids)
          const parts = Object.entries(result.supplier_hotel_ids).map(([k, v]) => `${k}: ${v}`)
          setMappingHint(parts.join(' · '))
        })
        .catch((err) => {
          if (cancelled) return
          setSupplierHotelIds({})
          setMappingHint(err instanceof Error ? err.message : 'Mapping lookup failed')
        })
        .finally(() => {
          if (!cancelled) setMappingLoading(false)
        })
    }, 400)

    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [atgHotelId, suppliers])

  const toggleSupplier = (code: SupplierCode, checked: boolean) => {
    setEnabledSuppliers((prev) => ({ ...prev, [code]: checked }))
  }

  const updateSupplierCurrency = (code: SupplierCode, value: string) => {
    setSupplierCurrencies((prev) => ({ ...prev, [code]: value.toUpperCase().slice(0, 3) }))
  }

  const updateContractCurrency = (code: SupplierCode, value: string) => {
    setContractCurrencies((prev) => ({ ...prev, [code]: value.toUpperCase().slice(0, 3) }))
  }

  const updateAssignmentTarget = (code: SupplierCode, value: AssignmentTarget) => {
    setAssignmentTargets((prev) => ({ ...prev, [code]: value }))
  }

  // Replace one instance's row list, leaving the code's other instances untouched.
  const setInstanceRows = (
    code: SupplierCode,
    instance: number,
    next: (rows: PackageRow[]) => PackageRow[],
  ) => {
    setSupplierPackages((prev) => ({
      ...prev,
      [code]: prev[code].map((rows, i) => (i === instance ? next(rows) : rows)),
    }))
  }

  const updateRow = (
    code: SupplierCode,
    instance: number,
    index: number,
    patch: Partial<PackageRow>,
  ) => {
    setInstanceRows(code, instance, (rows) =>
      rows.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    )
  }

  const addRow = (code: SupplierCode, instance: number) => {
    setInstanceRows(code, instance, (rows) => {
      const last = rows[rows.length - 1] ?? defaultPackageRow(rows.length)
      return [...rows, { ...last }]
    })
  }

  const removeRow = (code: SupplierCode, instance: number, index: number) => {
    setInstanceRows(code, instance, (rows) =>
      rows.length <= 1 ? rows : rows.filter((_, i) => i !== index),
    )
    // Keep the booking selection pointing at the same row after removal.
    setBookingRow((prev) => ({
      ...prev,
      [code]: prev[code].map((selected, i) => {
        if (i !== instance || selected === null) return selected
        if (selected === index) return null
        if (selected > index) return selected - 1
        return selected
      }),
    }))
  }

  // Radio-style selection: picking a row sets it; clicking the selected row
  // again clears it (so "no booking flow" stays reachable).
  const toggleBookingRow = (code: SupplierCode, instance: number, index: number) => {
    setBookingRow((prev) => ({
      ...prev,
      [code]: prev[code].map((selected, i) =>
        i === instance ? (selected === index ? null : index) : selected,
      ),
    }))
  }

  // A second (third, …) entry for the same supplier: its own package rows and its
  // own booking selection, sharing the code's currencies and assignment target.
  const addSupplierInstance = (code: SupplierCode) => {
    setSupplierPackages((prev) => ({ ...prev, [code]: [...prev[code], defaultPackageRows(3)] }))
    setBookingRow((prev) => ({ ...prev, [code]: [...prev[code], null] }))
  }

  const removeSupplierInstance = (code: SupplierCode, instance: number) => {
    setSupplierPackages((prev) => {
      if ((prev[code] ?? []).length <= 1) return prev
      return { ...prev, [code]: prev[code].filter((_, i) => i !== instance) }
    })
    setBookingRow((prev) => {
      if ((prev[code] ?? []).length <= 1) return prev
      return { ...prev, [code]: prev[code].filter((_, i) => i !== instance) }
    })
  }

  // Whether this scenario will provision BR at all — 'full' does it for the checkbox or
  // for SmartBooking, 'contract_br' always does, 'contract_only' never. Drives both the
  // markup inputs' visibility and whether their values are sent.
  const brWillProvision = depth === 'full' ? assignToBr || sbActive : depth === 'contract_br'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (suppliers.length === 0) {
      setFormError('Select at least one supplier')
      return
    }
    // SmartBooking needs at least one supplier feeding the SB group, else the
    // group would be created empty (mirrors the backend guard).
    if (depth === 'full' && sbActive && !suppliers.some((code) => assignmentTargets[code] !== 'apikey')) {
      setFormError('SmartBooking is on — set at least one supplier to SbGroup or Both')
      return
    }
    try {
      if (isTemplate && !templateLabel.trim()) {
        throw new Error('Give the template a label')
      }
      const request: ScenarioRequest = {
        namespace: namespace.trim(),
        check_in: checkIn,
        check_out: checkOut,
        atg_hotel_id: atgHotelId.trim(),
        supplier_hotel_ids: supplierHotelIds,
        // One entry per supplier instance, in order — the backend numbers repeated
        // codes 1, 2, 3… from this ordering and keys contracts/mocks accordingly.
        suppliers: suppliers.flatMap((code) =>
          (supplierPackages[code] ?? []).map((rows, instance) => {
            const parsed = parseRows(code, rows)
            return {
              code,
              contract_currency: contractCurrencies[code] || 'USD',
              assignment_target: assignmentTargets[code] ?? 'apikey',
              packages: {
                count: rows.length,
                room_basis: parsed.room_basis,
                room_names: parsed.room_names,
                // Configured suppliers carry their own default; the per-code constant
                // only covers the built-in five.
                supplier_currency:
                  supplierCurrencies[code] || DEFAULT_SUPPLIER_CURRENCIES[code] || 'USD',
                prices: parsed.prices,
                refundable: parsed.refundable,
                booking_package_index: bookingRow[code]?.[instance] ?? null,
                // Omitted when 'available' so the payload is unchanged for every
                // scenario that does not ask for a status.
                ...(canPrebook[code] !== undefined ? { can_prebook: canPrebook[code] } : {}),
                ...(prebookingStatus[code] && prebookingStatus[code] !== 'available'
                  ? { prebooking_status: prebookingStatus[code] }
                  : {}),
                ...(prebookingStatus[code] === 'price_changed' &&
                prebookingChangedPrice[code]?.trim()
                  ? { prebooking_changed_price: Number(prebookingChangedPrice[code]) }
                  : {}),
                // Omitted entirely when unused, so the request body stays exactly what it
                // was for every scenario that does not price explicitly.
                ...(parsed.markup
                  ? {
                      original_price_with_vat: parsed.original_price_with_vat,
                      markup: parsed.markup,
                    }
                  : {}),
              },
            }
          }),
        ),
        provisioning_depth: depth,
        // The backend rejects these outside 'full' rather than ignoring them, so don't
        // send stale values from a depth the user switched away from.
        assign_to_br: depth === 'full' ? assignToBr : false,
        sb_enabled: depth === 'full' ? sbActive : false,
        existing_api_key: depth === 'full' ? null : existingApiKey.trim() || null,
        // Same rule for the markup: only the depths that actually provision BR accept
        // them, and contract_only rejects them outright.
        ...(brWillProvision && staticMarkup.trim() ? { static_markup: staticMarkup.trim() } : {}),
        ...(brWillProvision && dynamicMarkup.trim() ? { dynamic_markup: dynamicMarkup.trim() } : {}),
      }
      await onSubmit(
        request,
        isTemplate
          ? {
              label: templateLabel.trim(),
              description: templateDescription.trim(),
              kind: templateKind,
            }
          : undefined,
      )
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Invalid form')
    }
  }

  return (
    <form className="wizard" onSubmit={handleSubmit}>
      <div className="wizard-section">
        <div className="wizard-section-title">{isTemplate ? 'Template' : 'Identity'}</div>
        {isTemplate ? (
          <div className="field-grid">
            <div className="field">
              <label>
                Label
                <input
                  value={templateLabel}
                  onChange={(e) => setTemplateLabel(e.target.value)}
                  required
                  maxLength={120}
                  placeholder="PreBooking SoldOut"
                />
              </label>
            </div>
            <div className="field">
              <label>
                Save under
                <select
                  value={templateKind}
                  onChange={(e) =>
                    setTemplateKind(e.target.value as 'templateBeddingMock' | 'preBookingMock')
                  }
                >
                  <option value="templateBeddingMock">Template Bedding Mock</option>
                  <option value="preBookingMock">PreBooking Mock</option>
                </select>
              </label>
            </div>
            <div className="field">
              <label>
                Description (optional)
                <input
                  value={templateDescription}
                  onChange={(e) => setTemplateDescription(e.target.value)}
                  maxLength={200}
                />
              </label>
            </div>
          </div>
        ) : (
          <div className="field-row">
            <div className="field">
              <label>
                Namespace
                <input
                  value={namespace}
                  onChange={(e) => setNamespace(e.target.value)}
                  required
                  minLength={3}
                  maxLength={64}
                  placeholder="qa-20260901-a1b2"
                />
              </label>
            </div>
            <button type="button" className="btn ghost" onClick={() => setNamespace(defaultNamespace())}>
              ↻ New
            </button>
          </div>
        )}
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Stay & hotel</div>
        <div className="field-grid">
          {/* Dates belong to a RUN, not a template — run-template supplies them. */}
          {!isTemplate && (
            <>
              <div className="field">
                <label>
                  Check-in
                  <input type="date" value={checkIn} onChange={(e) => setCheckIn(e.target.value)} required />
                </label>
              </div>
              <div className="field">
                <label>
                  Check-out
                  <input type="date" value={checkOut} onChange={(e) => setCheckOut(e.target.value)} required />
                </label>
              </div>
            </>
          )}
          <div className="field">
            <label>
              ATG hotel ID
              <input
                value={atgHotelId}
                onChange={(e) => setAtgHotelId(e.target.value)}
                required
                placeholder="1446194"
              />
            </label>
            {mappingLoading && (
              <p className="hint" style={{ marginTop: '0.35rem' }}>
                Resolving supplier hotel ids…
              </p>
            )}
            {!mappingLoading && mappingHint && (
              <p className="hint" style={{ marginTop: '0.35rem' }}>
                Supplier ids: {mappingHint}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Suppliers</div>
        <p className="hint" style={{ marginBottom: '0.75rem' }}>
          Each supplier has its own package rows — add/remove a row per package instead of editing separated text.
        </p>
        <div className="supplier-tiles supplier-tiles-wide">
          {availableSuppliers.map((meta) => {
            const enabled = enabledSuppliers[meta.code] ?? false
            const instances = supplierPackages[meta.code] ?? []
            return (
              <div
                key={meta.code}
                className="supplier-tile"
                style={{ ['--tile-color' as string]: meta.ui_color || 'var(--accent)' }}
              >
                <label className="supplier-tile-header">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => toggleSupplier(meta.code, e.target.checked)}
                  />
                  <div className="supplier-tile-body">
                    <strong>{meta.code}</strong>
                    <span>
                      {meta.name} · {meta.supplier_type} supplier
                      {!meta.ready && ` · ${meta.missing_count} thing(s) missing`}
                    </span>
                  </div>
                </label>
                {enabled && (
                  <div className="supplier-tile-content">
                    <label className="supplier-tile-field" style={{ maxWidth: '140px' }}>
                      Supplier Currency
                      <input
                        value={supplierCurrencies[meta.code] ?? ''}
                        onChange={(e) => updateSupplierCurrency(meta.code, e.target.value)}
                        maxLength={3}
                        placeholder={meta.default_supplier_currency}
                      />
                    </label>

                    <label className="supplier-tile-field" style={{ maxWidth: '140px' }}>
                      Contract Currency
                      <select
                        value={contractCurrencies[meta.code] ?? ''}
                        onChange={(e) => updateContractCurrency(meta.code, e.target.value)}
                      >
                        <option value="SAR">SAR</option>
                        <option value="AED">AED</option>
                        <option value="USD">USD</option>
                        <option value="EUR">EUR</option>
                      </select>
                    </label>

                    {/* Only for suppliers that actually have a PreBooking step — EXT
                        books straight off the distribution and has none. */}
                    {meta.log_types?.includes('PreBooking') && (
                      <label className="supplier-tile-field" style={{ maxWidth: '210px' }}>
                        Contract canPrebook
                        <select
                          value={
                            canPrebook[meta.code] === undefined
                              ? 'default'
                              : canPrebook[meta.code]
                                ? 'true'
                                : 'false'
                          }
                          onChange={(e) => {
                            const next =
                              e.target.value === 'default' ? undefined : e.target.value === 'true'
                            setCanPrebook((prev) => ({ ...prev, [meta.code]: next }))
                            // With no price check there is no status to observe, so
                            // reset it rather than let the backend reject the pair.
                            if (next === false) {
                              setPrebookingStatus((prev) => ({ ...prev, [meta.code]: 'available' }))
                              setPrebookingChangedPrice((prev) => ({ ...prev, [meta.code]: '' }))
                            }
                          }}
                        >
                          <option value="default">Leave as the contract has it</option>
                          <option value="true">Enabled</option>
                          <option value="false">Disabled (no prebook URL, no mock)</option>
                        </select>
                      </label>
                    )}

                    {meta.log_types?.includes('PreBooking') && canPrebook[meta.code] !== false && (
                      <label className="supplier-tile-field" style={{ maxWidth: '200px' }}>
                        PreBooking
                        <select
                          value={prebookingStatus[meta.code] ?? 'available'}
                          onChange={(e) => {
                            const next = e.target.value as PreBookingStatus
                            setPrebookingStatus((prev) => ({ ...prev, [meta.code]: next }))
                            // sold_out builds no Booking/GetOrder mocks, so a Book
                            // selection would be rejected by the backend. Clear it here
                            // rather than let the request 422.
                            if (next === 'sold_out') {
                              setBookingRow((prev) => ({
                                ...prev,
                                [meta.code]: (prev[meta.code] ?? []).map(() => null),
                              }))
                            }
                          }}
                        >
                          {PREBOOKING_STATUSES.map((s) => (
                            <option key={s.value} value={s.value}>
                              {s.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}

                    {prebookingStatus[meta.code] === 'price_changed' &&
                      canPrebook[meta.code] !== false && (
                      <label className="supplier-tile-field" style={{ maxWidth: '160px' }}>
                        Changed price
                        <input
                          value={prebookingChangedPrice[meta.code] ?? ''}
                          onChange={(e) =>
                            setPrebookingChangedPrice((prev) => ({
                              ...prev,
                              [meta.code]: e.target.value,
                            }))
                          }
                          placeholder="140"
                          spellCheck={false}
                          autoComplete="off"
                        />
                      </label>
                    )}

                    {sbActive && (
                      <label className="supplier-tile-field" style={{ maxWidth: '160px' }}>
                        Contract goes to
                        <select
                          value={assignmentTargets[meta.code]}
                          onChange={(e) => updateAssignmentTarget(meta.code, e.target.value as AssignmentTarget)}
                        >
                          <option value="apikey">ApiKey</option>
                          <option value="sbgroup">SB Group</option>
                          <option value="both">Both</option>
                        </select>
                      </label>
                    )}

                    {instances.map((rows, instance) => (
                      <div key={instance} className="supplier-instance">
                        {instances.length > 1 && (
                          <div className="supplier-instance-header">
                            <strong>
                              {meta.name} #{instance + 1}
                            </strong>
                            <button
                              type="button"
                              className="btn ghost package-row-remove"
                              onClick={() => removeSupplierInstance(meta.code, instance)}
                              title={`Remove this ${meta.name} entry`}
                            >
                              ×
                            </button>
                          </div>
                        )}
                        <div className="package-rows">
                          <div
                            className={`package-row package-row-head${
                              showExplicitPricing(meta.code, activeEnv) ? ' package-row-explicit' : ''
                            }`}
                          >
                            <span title="Build the Booking/GetOrder flow for this package">Book</span>
                            <span>Room basis</span>
                            <span>Room name</span>
                            <span>Price</span>
                            {showExplicitPricing(meta.code, activeEnv) && (
                              <>
                                <span title="Price minus markup — the pre-markup price">
                                  Orig. price (VAT)
                                </span>
                                <span title="Markup amount in supplier currency (totals.marketing_fee)">
                                  Markup
                                </span>
                              </>
                            )}
                            <span>Refundable</span>
                            <span />
                          </div>
                          {rows.map((row, index) => (
                            <div
                              key={index}
                              className={`package-row${
                                showExplicitPricing(meta.code, activeEnv) ? ' package-row-explicit' : ''
                              }`}
                            >
                              <input
                                type="radio"
                                name={`booking-${meta.code}-${instance}`}
                                checked={bookingRow[meta.code][instance] === index}
                                disabled={prebookingStatus[meta.code] === 'sold_out'}
                                // Toggle on click (clears when the selected row is re-clicked);
                                // onChange is a no-op required for a controlled radio.
                                onChange={() => {}}
                                onClick={() => toggleBookingRow(meta.code, instance, index)}
                                title={
                                  prebookingStatus[meta.code] === 'sold_out'
                                    ? 'A sold-out price check stops the scenario before booking, ' +
                                      'so there is no package to book.'
                                    : 'Select this package for the Booking/GetOrder flow (click again to clear)'
                                }
                              />
                              <input
                                value={row.roomBasis}
                                onChange={(e) =>
                                  updateRow(meta.code, instance, index, { roomBasis: e.target.value.toUpperCase() })
                                }
                                placeholder="RO"
                              />
                              <input
                                value={row.roomName}
                                onChange={(e) => updateRow(meta.code, instance, index, { roomName: e.target.value })}
                                placeholder={DEFAULT_ROOM_NAME}
                              />
                              <input
                                type="number"
                                value={row.price}
                                onChange={(e) => updateRow(meta.code, instance, index, { price: e.target.value })}
                                placeholder="100"
                              />
                              {showExplicitPricing(meta.code, activeEnv) && (
                                <>
                                  <input
                                    type="number"
                                    value={row.originalPriceWithVat ?? ''}
                                    onChange={(e) =>
                                      updateRow(meta.code, instance, index, {
                                        originalPriceWithVat: e.target.value,
                                      })
                                    }
                                    placeholder="optional"
                                    title="Pre-markup price with VAT"
                                  />
                                  <input
                                    type="number"
                                    value={row.markup ?? ''}
                                    onChange={(e) =>
                                      updateRow(meta.code, instance, index, { markup: e.target.value })
                                    }
                                    placeholder="optional"
                                    title="Markup amount in supplier currency"
                                  />
                                </>
                              )}
                              <input
                                type="checkbox"
                                checked={row.refundable}
                                onChange={(e) =>
                                  updateRow(meta.code, instance, index, { refundable: e.target.checked })
                                }
                              />
                              <button
                                type="button"
                                className="btn ghost package-row-remove"
                                onClick={() => removeRow(meta.code, instance, index)}
                                disabled={rows.length <= 1}
                                title="Remove package"
                              >
                                ×
                              </button>
                            </div>
                          ))}
                        </div>
                        <button type="button" className="btn ghost" onClick={() => addRow(meta.code, instance)}>
                          + Add package
                        </button>
                      </div>
                    ))}
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() => addSupplierInstance(meta.code)}
                      title={`Add a second ${meta.name} contract to this scenario`}
                    >
                      + Add another {meta.name}
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Provisioning</div>
        <p className="hint" style={{ marginBottom: '0.6rem' }}>
          How far to go past the mocks. Mocks and contracts are always created.
        </p>
        {PROVISIONING_DEPTHS.map((option) => (
          <label key={option.value} className="depth-option">
            <input
              type="radio"
              name="provisioning-depth"
              checked={depth === option.value}
              onChange={() => setDepth(option.value)}
            />
            <span>
              <strong>{option.label}</strong>
              <span className="hint">{option.hint}</span>
            </span>
          </label>
        ))}

        {depth !== 'full' && (
          <div className="depth-field">
            {/* Deliberately NOT .supplier-tile-field: that class uppercases both label and
                input, which would render an apiKey uid (lowercase by convention) as
                something other than what gets sent. */}
            <label htmlFor="existing-api-key">Existing apiKey (optional)</label>
            <input
              id="existing-api-key"
              value={existingApiKey}
              onChange={(e) => setExistingApiKey(e.target.value)}
              placeholder="tj-htl-test-bookable"
              spellCheck={false}
              autoComplete="off"
            />
            <p className="hint">
              Leave blank to create no apiKey at all. If given, this scenario's contracts are added
              to it — SMF never deletes an apiKey it didn't create, so teardown only detaches them.
              {depth === 'contract_br' &&
                ' It is also assigned to Room Static Markup In Percentage (3) and Room Dynamic Markup' +
                  ' In Percentage (4), so the contract conditions evaluate under it; only that' +
                  ' assignment is removed on teardown.'}
            </p>
            {/* contract_br provisions BR on the CONTRACTS, so it needs the markup fields
                too — and it has no assign-to-BR checkbox to hang them off. */}
            {depth === 'contract_br' && (
              <MarkupFields
                staticMarkup={staticMarkup}
                dynamicMarkup={dynamicMarkup}
                onStatic={setStaticMarkup}
                onDynamic={setDynamicMarkup}
                showDynamic={hasDynamicMarkup(activeEnv)}
              />
            )}
          </div>
        )}

        {/* BR + SmartBooking only apply to the full depth: both hang off a new apiKey. */}
        {depth === 'full' && (
          <>
            <label
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 500, marginTop: '0.75rem' }}
            >
              <input type="checkbox" checked={assignToBr} onChange={(e) => setAssignToBr(e.target.checked)} />
              {`Assign apiKey to BR (${
                hasDynamicMarkup(activeEnv) ? 'Static + Dynamic Markup rules' : 'Static Markup rule'
              })`}
            </label>
            <p className="hint" style={{ marginTop: '0.35rem' }}>
              On by default. Cleaned up automatically on teardown. Uncheck to skip BR assignment for
              this scenario.
            </p>
            {/* SmartBooking provisions BR whether or not the checkbox is ticked, so the
                fields follow what actually happens rather than the checkbox alone. */}
            {brWillProvision && (
              <MarkupFields
                staticMarkup={staticMarkup}
                dynamicMarkup={dynamicMarkup}
                onStatic={setStaticMarkup}
                onDynamic={setDynamicMarkup}
                showDynamic={hasDynamicMarkup(activeEnv)}
              />
            )}

            {hasSmartBooking(activeEnv) && (
              <>
                <label
                  style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 500, marginTop: '0.75rem' }}
                >
                  <input type="checkbox" checked={sbEnabled} onChange={(e) => setSbEnabled(e.target.checked)} />
                  Create apiKey with SmartBooking (creates an SB group)
                </label>
                <p className="hint" style={{ marginTop: '0.35rem' }}>
                  {sbEnabled
                    ? 'An SB group is created first, then attached to the apiKey. Choose per supplier (above) whether its contract goes to the ApiKey, the SB Group, or Both — at least one must be SB Group or Both.'
                    : 'Off by default. When on, each supplier can route its contract to the apiKey, the SB group, or both.'}
                </p>
              </>
            )}
          </>
        )}
      </div>

      <div className="form-footer">
        <p className="hint">
          {isTemplate ? (
            suppliers.length > 0 ? (
              <>
                Saves {supplierEntryLabels.join(' + ')} as a template. Dates and namespace
                are supplied when it runs; everything else here is stored.
              </>
            ) : (
              'Select at least one supplier'
            )
          ) : suppliers.length > 0 ? (
            <>
              Will create mocks for {supplierEntryLabels.join(' + ')}.{' '}
              {depth === 'full'
                ? 'Contracts + a new apiKey. '
                : depth === 'contract_br'
                  ? `Contracts + BR${
                      existingApiKey.trim()
                        ? `, added to ${existingApiKey.trim()} (also assigned to rules 3 + 4)`
                        : ', no apiKey'
                    }. `
                  : `Contracts only${existingApiKey.trim() ? `, added to ${existingApiKey.trim()}` : ', no apiKey'}. `}
              {(() => {
                const withBooking = supplierEntries.filter(
                  ({ code, instance }) => bookingRow[code][instance] !== null,
                )
                return withBooking.length > 0
                  ? `Booking flow: ${withBooking
                      .map(
                        ({ code, instance, label }) =>
                          `${label} (package #${(bookingRow[code][instance] ?? 0) + 1})`,
                      )
                      .join(', ')}.`
                  : 'No booking flow — search + package mocks only. Pick a "Book" package to add it.'
              })()}
            </>
          ) : (
            'Select at least one supplier'
          )}
        </p>
        <span style={{ display: 'flex', gap: '0.5rem' }}>
          {onCancel && (
            <button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>
              Cancel
            </button>
          )}
          <button type="submit" className="btn primary" disabled={busy || suppliers.length === 0}>
            {busy
              ? isTemplate
                ? 'Saving…'
                : 'Provisioning…'
              : isTemplate
                ? 'Save template →'
                : 'Create scenario →'}
          </button>
        </span>
      </div>

      {formError && <p className="error-text">{formError}</p>}
    </form>
  )
}
