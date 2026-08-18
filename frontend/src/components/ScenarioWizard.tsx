import { useEffect, useMemo, useState } from 'react'
import { resolveHotelMapping } from '../api/hotels'
import { PROVISIONING_DEPTHS } from '../types/scenario'
import type {
  AssignmentTarget,
  ProvisioningDepth,
  ScenarioRequest,
  SupplierCode,
} from '../types/scenario'
import { DEFAULT_ROOM_BASIS, DEFAULT_ROOM_NAME, DEFAULT_SUPPLIER_CURRENCIES } from '../types/scenario'

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
}

const DEFAULT_ROW_PRICES = [100, 200, 300]

function defaultPackageRow(index: number): PackageRow {
  return {
    roomBasis: DEFAULT_ROOM_BASIS,
    roomName: DEFAULT_ROOM_NAME,
    price: String(DEFAULT_ROW_PRICES[index] ?? DEFAULT_ROW_PRICES[DEFAULT_ROW_PRICES.length - 1]),
    refundable: true,
  }
}

function defaultPackageRows(count: number): PackageRow[] {
  return Array.from({ length: count }, (_, index) => defaultPackageRow(index))
}

interface ParsedRows {
  room_basis: string[]
  room_names: string[]
  prices: number[]
  refundable: boolean[]
}

function parseRows(supplierLabel: string, rows: PackageRow[]): ParsedRows {
  const room_basis: string[] = []
  const room_names: string[] = []
  const prices: number[] = []
  const refundable: boolean[] = []
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
  })
  return { room_basis, room_names, prices, refundable }
}

const SUPPLIER_CODES: SupplierCode[] = ['HBS', 'EXP', 'RHK', 'CHC', 'EXT']

const SUPPLIER_META: {
  code: SupplierCode
  className: string
  label: string
  description: string
  currencyPlaceholder: string
}[] = [
  { code: 'HBS', className: 'hbs', label: 'HBS', description: 'Hotelbeds · net supplier', currencyPlaceholder: 'EUR' },
  { code: 'EXP', className: 'exp', label: 'EXP', description: 'Expedia · override URLs', currencyPlaceholder: 'USD' },
  { code: 'RHK', className: 'rhk', label: 'RHK', description: 'RateHawk · WorldOTA B2B', currencyPlaceholder: 'USD' },
  { code: 'CHC', className: 'chc', label: 'CHC', description: 'Choice · net supplier', currencyPlaceholder: 'SAR' },
  { code: 'EXT', className: 'ext', label: 'EXT', description: 'Extranet · net supplier', currencyPlaceholder: 'EUR' },
]

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
  onSubmit: (request: ScenarioRequest) => Promise<void>
  busy: boolean
  initialTemplate?: ScenarioWizardTemplate
}

export function ScenarioWizard({ onSubmit, busy, initialTemplate }: Props) {
  const [namespace, setNamespace] = useState(defaultNamespace)
  const [checkIn, setCheckIn] = useState('2026-09-01')
  const [checkOut, setCheckOut] = useState('2026-09-03')
  const [atgHotelId, setAtgHotelId] = useState(() => initialTemplate?.atgHotelId ?? '1446194')
  const [supplierHotelIds, setSupplierHotelIds] = useState<Record<string, string>>({})
  const [mappingHint, setMappingHint] = useState<string | null>(null)
  const [mappingLoading, setMappingLoading] = useState(false)
  const [supplierCurrencies, setSupplierCurrencies] = useState<Record<SupplierCode, string>>(() => ({
    ...DEFAULT_SUPPLIER_CURRENCIES,
    ...(initialTemplate?.supplierCurrencies ?? {}),
  }))
  const [contractCurrencies, setContractCurrencies] = useState<Record<SupplierCode, string>>(() => ({
    HBS: initialTemplate?.contractCurrencies?.HBS ?? 'USD',
    EXP: initialTemplate?.contractCurrencies?.EXP ?? 'USD',
    RHK: initialTemplate?.contractCurrencies?.RHK ?? 'USD',
    CHC: initialTemplate?.contractCurrencies?.CHC ?? 'USD',
    EXT: initialTemplate?.contractCurrencies?.EXT ?? 'USD',
  }))
  // One entry per supplier INSTANCE: a supplier can be added more than once (two
  // EXP contracts at different prices in one scenario), so each code holds a list
  // of package-row sets rather than a single set. Templates carry one set, which
  // becomes instance 1.
  const [supplierPackages, setSupplierPackages] = useState<Record<SupplierCode, PackageRow[][]>>(() => {
    const rows = () => defaultPackageRows(3)
    return {
      HBS: templateInstances(initialTemplate?.packages?.HBS, rows),
      EXP: templateInstances(initialTemplate?.packages?.EXP, rows),
      RHK: templateInstances(initialTemplate?.packages?.RHK, rows),
      CHC: templateInstances(initialTemplate?.packages?.CHC, rows),
      EXT: templateInstances(initialTemplate?.packages?.EXT, rows),
    }
  })
  const [enabledSuppliers, setEnabledSuppliers] = useState<Record<SupplierCode, boolean>>(() => ({
    HBS: initialTemplate?.enabledSuppliers?.HBS ?? true,
    EXP: initialTemplate?.enabledSuppliers?.EXP ?? true,
    RHK: initialTemplate?.enabledSuppliers?.RHK ?? false,
    CHC: initialTemplate?.enabledSuppliers?.CHC ?? false,
    EXT: initialTemplate?.enabledSuppliers?.EXT ?? false,
  }))
  // Which package row the Booking/GetOrder flow is built for, per supplier instance.
  // null = no booking flow (only search + package mocks created).
  // One slot per supplier instance — must stay the same length as supplierPackages,
  // or toggling the Book radio on a template-loaded second instance would no-op.
  const [bookingRow, setBookingRow] = useState<Record<SupplierCode, (number | null)[]>>(() => {
    const slots = (code: SupplierCode) =>
      templateInstances(initialTemplate?.packages?.[code], () => []).map(() => null)
    return {
      HBS: slots('HBS'),
      EXP: slots('EXP'),
      RHK: slots('RHK'),
      CHC: slots('CHC'),
      EXT: slots('EXT'),
    }
  })
  const [assignToBr, setAssignToBr] = useState(true)
  // How far provisioning goes. 'full' keeps the historical behaviour.
  const [depth, setDepth] = useState<ProvisioningDepth>('full')
  const [existingApiKey, setExistingApiKey] = useState('')
  // SmartBooking: create the apiKey with SB enabled, and per-supplier route each
  // contract to the apiKey, the SB group, or both (default apikey).
  const [sbEnabled, setSbEnabled] = useState(() => initialTemplate?.sbEnabled ?? false)
  const [assignmentTargets, setAssignmentTargets] = useState<Record<SupplierCode, AssignmentTarget>>(() => ({
    HBS: initialTemplate?.assignmentTargets?.HBS ?? 'apikey',
    EXP: initialTemplate?.assignmentTargets?.EXP ?? 'apikey',
    RHK: initialTemplate?.assignmentTargets?.RHK ?? 'apikey',
    CHC: initialTemplate?.assignmentTargets?.CHC ?? 'apikey',
    EXT: initialTemplate?.assignmentTargets?.EXT ?? 'apikey',
  }))
  const [formError, setFormError] = useState<string | null>(null)

  const suppliers = useMemo(
    () => SUPPLIER_CODES.filter((code) => enabledSuppliers[code]),
    [enabledSuppliers],
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
      if (prev[code].length <= 1) return prev
      return { ...prev, [code]: prev[code].filter((_, i) => i !== instance) }
    })
    setBookingRow((prev) => {
      if (prev[code].length <= 1) return prev
      return { ...prev, [code]: prev[code].filter((_, i) => i !== instance) }
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (suppliers.length === 0) {
      setFormError('Select at least one supplier')
      return
    }
    // SmartBooking needs at least one supplier feeding the SB group, else the
    // group would be created empty (mirrors the backend guard).
    if (depth === 'full' && sbEnabled && !suppliers.some((code) => assignmentTargets[code] !== 'apikey')) {
      setFormError('SmartBooking is on — set at least one supplier to SbGroup or Both')
      return
    }
    try {
      const request: ScenarioRequest = {
        namespace: namespace.trim(),
        check_in: checkIn,
        check_out: checkOut,
        atg_hotel_id: atgHotelId.trim(),
        supplier_hotel_ids: supplierHotelIds,
        // One entry per supplier instance, in order — the backend numbers repeated
        // codes 1, 2, 3… from this ordering and keys contracts/mocks accordingly.
        suppliers: suppliers.flatMap((code) =>
          supplierPackages[code].map((rows, instance) => {
            const parsed = parseRows(code, rows)
            return {
              code,
              contract_currency: contractCurrencies[code] || 'USD',
              assignment_target: assignmentTargets[code],
              packages: {
                count: rows.length,
                room_basis: parsed.room_basis,
                room_names: parsed.room_names,
                supplier_currency: supplierCurrencies[code] || DEFAULT_SUPPLIER_CURRENCIES[code],
                prices: parsed.prices,
                refundable: parsed.refundable,
                booking_package_index: bookingRow[code][instance] ?? null,
              },
            }
          }),
        ),
        provisioning_depth: depth,
        // The backend rejects these outside 'full' rather than ignoring them, so don't
        // send stale values from a depth the user switched away from.
        assign_to_br: depth === 'full' ? assignToBr : false,
        sb_enabled: depth === 'full' ? sbEnabled : false,
        existing_api_key: depth === 'full' ? null : existingApiKey.trim() || null,
      }
      await onSubmit(request)
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Invalid form')
    }
  }

  return (
    <form className="wizard" onSubmit={handleSubmit}>
      <div className="wizard-section">
        <div className="wizard-section-title">Identity</div>
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
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Stay & hotel</div>
        <div className="field-grid">
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
          {SUPPLIER_META.map((meta) => {
            const enabled = enabledSuppliers[meta.code]
            const instances = supplierPackages[meta.code]
            return (
              <div key={meta.code} className={`supplier-tile ${meta.className}`}>
                <label className="supplier-tile-header">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => toggleSupplier(meta.code, e.target.checked)}
                  />
                  <div className="supplier-tile-body">
                    <strong>{meta.label}</strong>
                    <span>{meta.description}</span>
                  </div>
                </label>
                {enabled && (
                  <div className="supplier-tile-content">
                    <label className="supplier-tile-field" style={{ maxWidth: '140px' }}>
                      Supplier Currency
                      <input
                        value={supplierCurrencies[meta.code]}
                        onChange={(e) => updateSupplierCurrency(meta.code, e.target.value)}
                        maxLength={3}
                        placeholder={meta.currencyPlaceholder}
                      />
                    </label>

                    <label className="supplier-tile-field" style={{ maxWidth: '140px' }}>
                      Contract Currency
                      <select
                        value={contractCurrencies[meta.code]}
                        onChange={(e) => updateContractCurrency(meta.code, e.target.value)}
                      >
                        <option value="SAR">SAR</option>
                        <option value="AED">AED</option>
                        <option value="USD">USD</option>
                        <option value="EUR">EUR</option>
                      </select>
                    </label>

                    {sbEnabled && (
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
                              {meta.label} #{instance + 1}
                            </strong>
                            <button
                              type="button"
                              className="btn ghost package-row-remove"
                              onClick={() => removeSupplierInstance(meta.code, instance)}
                              title={`Remove this ${meta.label} entry`}
                            >
                              ×
                            </button>
                          </div>
                        )}
                        <div className="package-rows">
                          <div className="package-row package-row-head">
                            <span title="Build the Booking/GetOrder flow for this package">Book</span>
                            <span>Room basis</span>
                            <span>Room name</span>
                            <span>Price</span>
                            <span>Refundable</span>
                            <span />
                          </div>
                          {rows.map((row, index) => (
                            <div key={index} className="package-row">
                              <input
                                type="radio"
                                name={`booking-${meta.code}-${instance}`}
                                checked={bookingRow[meta.code][instance] === index}
                                // Toggle on click (clears when the selected row is re-clicked);
                                // onChange is a no-op required for a controlled radio.
                                onChange={() => {}}
                                onClick={() => toggleBookingRow(meta.code, instance, index)}
                                title="Select this package for the Booking/GetOrder flow (click again to clear)"
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
                      title={`Add a second ${meta.label} contract to this scenario`}
                    >
                      + Add another {meta.label}
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
          <label className="supplier-tile-field" style={{ maxWidth: '340px', marginTop: '0.5rem' }}>
            Existing apiKey (optional)
            <input
              value={existingApiKey}
              onChange={(e) => setExistingApiKey(e.target.value)}
              placeholder="tj-htl-test-bookable"
            />
            <span className="hint">
              Leave blank to create no apiKey at all. If given, this scenario's contracts are added
              to it — SMF never deletes an apiKey it didn't create, so teardown only detaches them.
            </span>
          </label>
        )}

        {/* BR + SmartBooking only apply to the full depth: both hang off a new apiKey. */}
        {depth === 'full' && (
          <>
            <label
              style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 500, marginTop: '0.75rem' }}
            >
              <input type="checkbox" checked={assignToBr} onChange={(e) => setAssignToBr(e.target.checked)} />
              Assign apiKey to BR (Static + Dynamic Markup rules)
            </label>
            <p className="hint" style={{ marginTop: '0.35rem' }}>
              On by default. Cleaned up automatically on teardown. Uncheck to skip BR assignment for
              this scenario.
            </p>

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
      </div>

      <div className="form-footer">
        <p className="hint">
          {suppliers.length > 0 ? (
            <>
              Will create mocks for {supplierEntryLabels.join(' + ')}.{' '}
              {depth === 'full'
                ? 'Contracts + a new apiKey. '
                : depth === 'contract_br'
                  ? `Contracts + BR${existingApiKey.trim() ? `, added to ${existingApiKey.trim()}` : ', no apiKey'}. `
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
        <button type="submit" className="btn primary" disabled={busy || suppliers.length === 0}>
          {busy ? 'Provisioning…' : 'Create scenario →'}
        </button>
      </div>

      {formError && <p className="error-text">{formError}</p>}
    </form>
  )
}
