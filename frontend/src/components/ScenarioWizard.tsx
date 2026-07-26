import { useEffect, useMemo, useState } from 'react'
import { resolveHotelMapping } from '../api/hotels'
import type { ScenarioRequest, SupplierCode } from '../types/scenario'
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
  packages?: Partial<Record<SupplierCode, PackageRow[]>>
  supplierCurrencies?: Partial<Record<SupplierCode, string>>
  contractCurrencies?: Partial<Record<SupplierCode, string>>
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
  const [, setSupplierHotelIds] = useState<Record<string, string>>({})
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
  }))
  const [supplierPackages, setSupplierPackages] = useState<Record<SupplierCode, PackageRow[]>>(() => ({
    HBS: initialTemplate?.packages?.HBS ?? defaultPackageRows(3),
    EXP: initialTemplate?.packages?.EXP ?? defaultPackageRows(3),
    RHK: initialTemplate?.packages?.RHK ?? defaultPackageRows(3),
    CHC: initialTemplate?.packages?.CHC ?? defaultPackageRows(3),
  }))
  const [enabledSuppliers, setEnabledSuppliers] = useState<Record<SupplierCode, boolean>>(() => ({
    HBS: initialTemplate?.enabledSuppliers?.HBS ?? true,
    EXP: initialTemplate?.enabledSuppliers?.EXP ?? true,
    RHK: initialTemplate?.enabledSuppliers?.RHK ?? false,
    CHC: initialTemplate?.enabledSuppliers?.CHC ?? false,
  }))
  const [assignToBr, setAssignToBr] = useState(true)
  const [formError, setFormError] = useState<string | null>(null)

  const suppliers = useMemo(
    () => SUPPLIER_CODES.filter((code) => enabledSuppliers[code]),
    [enabledSuppliers],
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

  const updateRow = (code: SupplierCode, index: number, patch: Partial<PackageRow>) => {
    setSupplierPackages((prev) => {
      const rows = prev[code].map((row, i) => (i === index ? { ...row, ...patch } : row))
      return { ...prev, [code]: rows }
    })
  }

  const addRow = (code: SupplierCode) => {
    setSupplierPackages((prev) => {
      const rows = prev[code]
      const last = rows[rows.length - 1] ?? defaultPackageRow(rows.length)
      return { ...prev, [code]: [...rows, { ...last }] }
    })
  }

  const removeRow = (code: SupplierCode, index: number) => {
    setSupplierPackages((prev) => {
      const rows = prev[code]
      if (rows.length <= 1) return prev
      return { ...prev, [code]: rows.filter((_, i) => i !== index) }
    })
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (suppliers.length === 0) {
      setFormError('Select at least one supplier')
      return
    }
    try {
      const request: ScenarioRequest = {
        namespace: namespace.trim(),
        check_in: checkIn,
        check_out: checkOut,
        atg_hotel_id: atgHotelId.trim(),
        suppliers: suppliers.map((code) => {
          const rows = supplierPackages[code]
          const parsed = parseRows(code, rows)
          return {
            code,
            contract_currency: contractCurrencies[code] || 'USD',
            packages: {
              count: rows.length,
              room_basis: parsed.room_basis,
              room_names: parsed.room_names,
              supplier_currency: supplierCurrencies[code] || DEFAULT_SUPPLIER_CURRENCIES[code],
              prices: parsed.prices,
              refundable: parsed.refundable,
            },
          }
        }),
        assign_to_br: assignToBr,
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
            const rows = supplierPackages[meta.code]
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

                    <div className="package-rows">
                      <div className="package-row package-row-head">
                        <span>Room basis</span>
                        <span>Room name</span>
                        <span>Price</span>
                        <span>Refundable</span>
                        <span />
                      </div>
                      {rows.map((row, index) => (
                        <div key={index} className="package-row">
                          <input
                            value={row.roomBasis}
                            onChange={(e) => updateRow(meta.code, index, { roomBasis: e.target.value.toUpperCase() })}
                            placeholder="RO"
                          />
                          <input
                            value={row.roomName}
                            onChange={(e) => updateRow(meta.code, index, { roomName: e.target.value })}
                            placeholder={DEFAULT_ROOM_NAME}
                          />
                          <input
                            type="number"
                            value={row.price}
                            onChange={(e) => updateRow(meta.code, index, { price: e.target.value })}
                            placeholder="100"
                          />
                          <input
                            type="checkbox"
                            checked={row.refundable}
                            onChange={(e) => updateRow(meta.code, index, { refundable: e.target.checked })}
                          />
                          <button
                            type="button"
                            className="btn ghost package-row-remove"
                            onClick={() => removeRow(meta.code, index)}
                            disabled={rows.length <= 1}
                            title="Remove package"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>
                    <button type="button" className="btn ghost" onClick={() => addRow(meta.code)}>
                      + Add package
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      <div className="wizard-section">
        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 500 }}>
          <input type="checkbox" checked={assignToBr} onChange={(e) => setAssignToBr(e.target.checked)} />
          Assign apiKey to BR (Static + Dynamic Markup rules)
        </label>
        <p className="hint" style={{ marginTop: '0.35rem' }}>
          On by default. Cleaned up automatically on teardown. Uncheck to skip BR assignment for this scenario.
        </p>
      </div>

      <div className="form-footer">
        <p className="hint">
          {suppliers.length > 0
            ? `Will create mocks for ${suppliers.join(' + ')}`
            : 'Select at least one supplier'}
        </p>
        <button type="submit" className="btn primary" disabled={busy || suppliers.length === 0}>
          {busy ? 'Provisioning…' : 'Create scenario →'}
        </button>
      </div>

      {formError && <p className="error-text">{formError}</p>}
    </form>
  )
}
