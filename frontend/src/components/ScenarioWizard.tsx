import { useEffect, useMemo, useState } from 'react'
import { resolveHotelMapping } from '../api/hotels'
import type { ScenarioRequest, SupplierCode } from '../types/scenario'

function defaultNamespace() {
  const d = new Date()
  const stamp = d.toISOString().slice(0, 10).replace(/-/g, '')
  const suffix = Math.random().toString(36).slice(2, 6)
  return `qa-${stamp}-${suffix}`
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
  const [pricesText, setPricesText] = useState('100, 200, 300')
  const [refundableText, setRefundableText] = useState('true, true, false')
  const [enableHbs, setEnableHbs] = useState(true)
  const [enableExp, setEnableExp] = useState(true)
  const [enableRhk, setEnableRhk] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  const suppliers = useMemo(() => {
    const codes: SupplierCode[] = []
    if (enableHbs) codes.push('HBS')
    if (enableExp) codes.push('EXP')
    if (enableRhk) codes.push('RHK')
    return codes
  }, [enableHbs, enableExp, enableRhk])

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
          <div className="field">
            <label>
              Prices (comma-separated)
              <input value={pricesText} onChange={(e) => setPricesText(e.target.value)} placeholder="100, 200, 300" />
            </label>
          </div>
          <div className="field">
            <label>
              Refundable (true/false)
              <input
                value={refundableText}
                onChange={(e) => setRefundableText(e.target.value)}
                placeholder="true, true, false"
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
            </div>
          </label>
          <label className="supplier-tile exp">
            <input type="checkbox" checked={enableExp} onChange={(e) => setEnableExp(e.target.checked)} />
            <div className="supplier-tile-body">
              <strong>EXP</strong>
              <span>Expedia · override URLs</span>
            </div>
          </label>
          <label className="supplier-tile rhk">
            <input type="checkbox" checked={enableRhk} onChange={(e) => setEnableRhk(e.target.checked)} />
            <div className="supplier-tile-body">
              <strong>RHK</strong>
              <span>RateHawk · WorldOTA B2B</span>
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
