import { useEffect, useMemo, useState } from 'react'
import { resolveHotelMapping } from '../api/hotels'
import type { ScenarioRequest, SupplierCode } from '../types/scenario'
import { DEFAULT_ROOM_NAME, DEFAULT_SUPPLIER_CURRENCIES } from '../types/scenario'

function defaultNamespace() {
  const d = new Date()
  const stamp = d.toISOString().slice(0, 10).replace(/-/g, '')
  const suffix = Math.random().toString(36).slice(2, 6)
  return `qa-${stamp}-${suffix}`
}

const ROOM_NAME_SEP = ' - '

function defaultRoomNamesText(count: number): string {
  return Array.from({ length: count }, () => DEFAULT_ROOM_NAME).join(ROOM_NAME_SEP)
}

function defaultPricesText(count: number): string {
  const base = [100, 200, 300]
  const prices = Array.from({ length: count }, (_, index) => base[index] ?? base[base.length - 1] ?? 100)
  return prices.join(', ')
}

function defaultRefundableText(count: number): string {
  const base = [true, true, false]
  const flags = Array.from({ length: count }, (_, index) => base[index] ?? false)
  return flags.map(String).join(', ')
}

function parsePrices(text: string, count: number): number[] {
  const parts = text
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean)
    .map(Number)
  if (parts.some((n) => Number.isNaN(n))) {
    throw new Error('Prices must be comma-separated numbers')
  }
  if (parts.length < count) {
    const last = parts[parts.length - 1] ?? 100
    while (parts.length < count) parts.push(last)
  }
  return parts.slice(0, count)
}

function parseRefundable(text: string, count: number): boolean[] {
  if (!text.trim()) return Array.from({ length: count }, () => false)
  const parts = text.split(',').map((p) => p.trim().toLowerCase())
  const flags = parts.map((p) => p === 'true' || p === '1' || p === 'yes')
  while (flags.length < count) flags.push(false)
  return flags.slice(0, count)
}

function parseRoomNames(text: string, count: number): string[] {
  const parts = text
    .split(/\s+-\s+/)
    .map((p) => p.trim())
    .filter(Boolean)
  if (parts.length === 0) {
    return Array.from({ length: count }, () => DEFAULT_ROOM_NAME)
  }
  if (parts.length < count) {
    const last = parts[parts.length - 1] ?? DEFAULT_ROOM_NAME
    while (parts.length < count) parts.push(last)
  }
  return parts.slice(0, count)
}

interface Props {
  onSubmit: (request: ScenarioRequest) => Promise<void>
  busy: boolean
}

export function ScenarioWizard({ onSubmit, busy }: Props) {
  const [namespace, setNamespace] = useState(defaultNamespace)
  const [checkIn, setCheckIn] = useState('2026-09-01')
  const [checkOut, setCheckOut] = useState('2026-09-03')
  const [atgHotelId, setAtgHotelId] = useState('1446194')
  const [, setSupplierHotelIds] = useState<Record<string, string>>({})
  const [mappingHint, setMappingHint] = useState<string | null>(null)
  const [mappingLoading, setMappingLoading] = useState(false)
  const [packageCount, setPackageCount] = useState(3)
  const [roomBasis, setRoomBasis] = useState('RO')
  const [roomNamesText, setRoomNamesText] = useState(() => defaultRoomNamesText(3))
  const [pricesText, setPricesText] = useState(() => defaultPricesText(3))
  const [refundableText, setRefundableText] = useState(() => defaultRefundableText(3))
  const [supplierCurrencies, setSupplierCurrencies] = useState<Record<SupplierCode, string>>({
    ...DEFAULT_SUPPLIER_CURRENCIES,
  })
  const [enableHbs, setEnableHbs] = useState(true)
  const [enableExp, setEnableExp] = useState(true)
  const [enableRhk, setEnableRhk] = useState(false)
  const [enableChc, setEnableChc] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const suppliers = useMemo(() => {
    const codes: SupplierCode[] = []
    if (enableHbs) codes.push('HBS')
    if (enableExp) codes.push('EXP')
    if (enableRhk) codes.push('RHK')
    if (enableChc) codes.push('CHC')
    return codes
  }, [enableHbs, enableExp, enableRhk, enableChc])

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

  useEffect(() => {
    setRoomNamesText((prev) => parseRoomNames(prev, packageCount).join(ROOM_NAME_SEP))
    setPricesText((prev) => {
      try {
        return parsePrices(prev, packageCount).join(', ')
      } catch {
        return defaultPricesText(packageCount)
      }
    })
    setRefundableText((prev) => parseRefundable(prev, packageCount).map(String).join(', '))
  }, [packageCount])

  const updateSupplierCurrency = (code: SupplierCode, value: string) => {
    setSupplierCurrencies((prev) => ({ ...prev, [code]: value.toUpperCase().slice(0, 3) }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (suppliers.length === 0) {
      setFormError('Select at least one supplier')
      return
    }
    try {
      const prices = parsePrices(pricesText, packageCount)
      const refundable = parseRefundable(refundableText, packageCount)
      const room_names = parseRoomNames(roomNamesText, packageCount)
      const request: ScenarioRequest = {
        namespace: namespace.trim(),
        check_in: checkIn,
        check_out: checkOut,
        atg_hotel_id: atgHotelId.trim(),
        suppliers: suppliers.map((code) => ({
          code,
          packages: {
            count: packageCount,
            room_basis: roomBasis,
            room_names,
            supplier_currency: supplierCurrencies[code] || DEFAULT_SUPPLIER_CURRENCIES[code],
            prices,
            refundable,
          },
        })),
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
        <div className="wizard-section-title">Packages</div>
        <div className="field-grid">
          <div className="field">
            <label>
              Count
              <input
                type="number"
                min={1}
                max={20}
                value={packageCount}
                onChange={(e) => setPackageCount(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Room basis
              <select value={roomBasis} onChange={(e) => setRoomBasis(e.target.value)}>
                <option value="RO">RO — Room only</option>
                <option value="BB">BB — Bed & breakfast</option>
                <option value="HB">HB — Half board</option>
                <option value="FB">FB — Full board</option>
              </select>
            </label>
          </div>
        </div>
        <div className="field-grid" style={{ marginTop: '0.85rem' }}>
          <div className="field field-wide">
            <label>
              Room names (- separated, one per package)
              <input
                value={roomNamesText}
                onChange={(e) => setRoomNamesText(e.target.value)}
                placeholder={defaultRoomNamesText(packageCount)}
              />
            </label>
            <p className="hint" style={{ marginTop: '0.35rem' }}>
              HBS: set on mock per package. CHC: display name from hotel content cache by roomId.
            </p>
          </div>
        </div>
        <div className="field-grid" style={{ marginTop: '0.85rem' }}>
          <div className="field">
            <label>
              Prices (comma-separated)
              <input
                value={pricesText}
                onChange={(e) => setPricesText(e.target.value)}
                placeholder={defaultPricesText(packageCount)}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Refundable (true/false)
              <input
                value={refundableText}
                onChange={(e) => setRefundableText(e.target.value)}
                placeholder={defaultRefundableText(packageCount)}
              />
            </label>
          </div>
        </div>
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Suppliers</div>
        <div className="supplier-tiles">
          <label className="supplier-tile hbs">
            <input type="checkbox" checked={enableHbs} onChange={(e) => setEnableHbs(e.target.checked)} />
            <div className="supplier-tile-body">
              <strong>HBS</strong>
              <span>Hotelbeds · net supplier</span>
              {enableHbs && (
                <label className="supplier-tile-field" onClick={(e) => e.preventDefault()}>
                  Currency
                  <input
                    value={supplierCurrencies.HBS}
                    onChange={(e) => updateSupplierCurrency('HBS', e.target.value)}
                    maxLength={3}
                    placeholder="EUR"
                  />
                </label>
              )}
            </div>
          </label>
          <label className="supplier-tile exp">
            <input type="checkbox" checked={enableExp} onChange={(e) => setEnableExp(e.target.checked)} />
            <div className="supplier-tile-body">
              <strong>EXP</strong>
              <span>Expedia · override URLs</span>
              {enableExp && (
                <label className="supplier-tile-field" onClick={(e) => e.preventDefault()}>
                  Currency
                  <input
                    value={supplierCurrencies.EXP}
                    onChange={(e) => updateSupplierCurrency('EXP', e.target.value)}
                    maxLength={3}
                    placeholder="USD"
                  />
                </label>
              )}
            </div>
          </label>
          <label className="supplier-tile rhk">
            <input type="checkbox" checked={enableRhk} onChange={(e) => setEnableRhk(e.target.checked)} />
            <div className="supplier-tile-body">
              <strong>RHK</strong>
              <span>RateHawk · WorldOTA B2B</span>
              {enableRhk && (
                <label className="supplier-tile-field" onClick={(e) => e.preventDefault()}>
                  Currency
                  <input
                    value={supplierCurrencies.RHK}
                    onChange={(e) => updateSupplierCurrency('RHK', e.target.value)}
                    maxLength={3}
                    placeholder="USD"
                  />
                </label>
              )}
            </div>
          </label>
          <label className="supplier-tile chc">
            <input type="checkbox" checked={enableChc} onChange={(e) => setEnableChc(e.target.checked)} />
            <div className="supplier-tile-body">
              <strong>CHC</strong>
              <span>Choice · net supplier</span>
              {enableChc && (
                <label className="supplier-tile-field" onClick={(e) => e.preventDefault()}>
                  Currency
                  <input
                    value={supplierCurrencies.CHC}
                    onChange={(e) => updateSupplierCurrency('CHC', e.target.value)}
                    maxLength={3}
                    placeholder="SAR"
                  />
                </label>
              )}
            </div>
          </label>
        </div>
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
