import { useEffect, useMemo, useState } from 'react'
import { fetchCrawlaPackagesAnchor, fetchCrawlaSearchAnchor } from '../api/crawla'
import type {
  CrawlaAnchorPackagesResponse,
  CrawlaAnchorSearchResponse,
  CrawlaBucket,
  CrawlaPackagePriceMode,
  CrawlaScenarioRequest,
} from '../types/crawla'

function defaultNamespace() {
  const d = new Date()
  const stamp = d.toISOString().slice(0, 10).replace(/-/g, '')
  const suffix = Math.random().toString(36).slice(2, 6)
  return `crawla-${stamp}-${suffix}`
}

function formatLocalDate(date: Date) {
  const year = date.getFullYear()
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const day = `${date.getDate()}`.padStart(2, '0')
  return `${year}-${month}-${day}`
}

function defaultCheckIn() {
  const date = new Date()
  date.setDate(date.getDate() + 1)
  return formatLocalDate(date)
}

function addDays(dateValue: string, days: number) {
  const date = new Date(`${dateValue}T00:00:00`)
  date.setDate(date.getDate() + days)
  return formatLocalDate(date)
}

function parseHotelIds(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((part) => part.trim()).filter(Boolean))]
}

function suggestPrices(base: number, bucket: CrawlaBucket) {
  const expPrices: Record<CrawlaBucket, number> = {
    CRAWLA_LOWER:      base * 1.15,  // EXP higher than Crawla → Crawla wins
    EXPEDIA_LOWER:     base * 0.85,  // EXP lower  than Crawla → Expedia wins
    EQUAL:             base,         // EXP ≈ Crawla
    ONLY_EXPEDIA:      500,          // no Crawla anchor; fixed base
    ONLY_CRAWLA:       base,         // EXP excluded; base kept for reference
    CHEAPEST_L2_GROSS: base * 0.85,  // EXP < Crawla → EXP is cheapest gross → L2 fires
  }
  const exp = expPrices[bucket]
  // HBS is always 65% less than EXP (60-70% requirement, midpoint = 65%)
  return {
    exp: Number(exp.toFixed(2)),
    hbs: Number((exp * 0.35).toFixed(2)),
  }
}

function formatMoney(value: number | null | undefined) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(2)
}

function buildPriceSeries(base: number, count: number, mode: CrawlaPackagePriceMode, step: number) {
  return Array.from({ length: count }, (_, index) => {
    if (mode === 'INCREASE') return Number((base + step * index).toFixed(2))
    if (mode === 'DECREASE') return Number(Math.max(base - step * index, 0.01).toFixed(2))
    return Number(base.toFixed(2))
  })
}

function pickDefaultOfferId(
  hotel: CrawlaAnchorPackagesResponse['hotels'][number] | undefined,
) {
  const offers = hotel?.data ?? []
  if (!offers.length) return ''
  const minPrice = hotel?.min_price
  const exactMatch = offers.find((offer) => typeof minPrice === 'number' && offer.total_amount === minPrice)
  return exactMatch?.room_id ?? offers[0].room_id
}

function offerLabel(offer: CrawlaAnchorPackagesResponse['hotels'][number]['data'][number]) {
  return `${offer.room_name} · ${offer.room_basis ?? offer.meal ?? 'RO'} · ${formatMoney(offer.total_amount)} · ${offer.room_id}`
}

function searchLabel(item: CrawlaAnchorSearchResponse['data'][number]) {
  return `${item.room_name ?? 'Room n/a'} · ${item.room_basis ?? 'RO'} · ${formatMoney(item.total_amount ?? item.min_price)}`
}

interface Props {
  onSubmit: (request: CrawlaScenarioRequest) => Promise<void>
  busy: boolean
}

export function CrawlaMocksWizard({ onSubmit, busy }: Props) {
  const [namespace, setNamespace] = useState(defaultNamespace)
  const initialCheckIn = defaultCheckIn()
  const [checkIn, setCheckIn] = useState(initialCheckIn)
  const [checkOut, setCheckOut] = useState(() => addDays(initialCheckIn, 2))
  const [hotelIdsText, setHotelIdsText] = useState('1043546')
  const [bucket, setBucket] = useState<CrawlaBucket>('CRAWLA_LOWER')

  const [searchAnchors, setSearchAnchors] = useState<CrawlaAnchorSearchResponse['data']>([])
  const [packagesAnchors, setPackagesAnchors] = useState<CrawlaAnchorPackagesResponse['hotels']>([])
  const [selectedSearchId, setSelectedSearchId] = useState<string>('')
  const [selectedPackageHotelId, setSelectedPackageHotelId] = useState<string>('')
  const [selectedOfferId, setSelectedOfferId] = useState<string>('')

  const [searchExpPrice, setSearchExpPrice] = useState(0)
  const [searchHbsPrice, setSearchHbsPrice] = useState(0)
  const [packageExpPrice, setPackageExpPrice] = useState(0)
  const [packageHbsPrice, setPackageHbsPrice] = useState(0)
  const [packageCount, setPackageCount] = useState(1)
  const [packagePriceMode, setPackagePriceMode] = useState<CrawlaPackagePriceMode>('SAME')
  const [packagePriceStep, setPackagePriceStep] = useState(10)
  const [formError, setFormError] = useState<string | null>(null)
  const [searchLoading, setSearchLoading] = useState(false)
  const [packagesLoading, setPackagesLoading] = useState(false)
  const [showPackageAnchors, setShowPackageAnchors] = useState(false)
  const [showPackagePreview, setShowPackagePreview] = useState(false)
  const [searchRawResponse, setSearchRawResponse] = useState<unknown>(null)
  const [packagesRawResponse, setPackagesRawResponse] = useState<unknown>(null)
  const [showSearchRaw, setShowSearchRaw] = useState(false)
  const [showPackagesRaw, setShowPackagesRaw] = useState(false)

  const parsedHotelIds = useMemo(() => parseHotelIds(hotelIdsText), [hotelIdsText])
  const selectedSearch = searchAnchors.find((item) => item.atg_id === selectedSearchId) ?? searchAnchors[0]
  const selectedPackageHotel =
    packagesAnchors.find((item) => item.atg_id === selectedPackageHotelId) ?? packagesAnchors[0]
  const selectedOffer = useMemo(() => {
    if (!selectedPackageHotel?.data?.length) return undefined
    return selectedPackageHotel.data.find((item) => item.room_id === selectedOfferId) ?? selectedPackageHotel.data[0]
  }, [selectedOfferId, selectedPackageHotel])

  const searchBase = selectedSearch?.total_amount ?? selectedSearch?.min_price ?? 100
  const packageBase = selectedOffer?.total_amount ?? selectedPackageHotel?.min_price ?? searchBase
  const packageHbsSeries = buildPriceSeries(packageHbsPrice, packageCount, packagePriceMode, packagePriceStep)
  const packageExpSeries = buildPriceSeries(packageExpPrice, packageCount, packagePriceMode, packagePriceStep)

  useEffect(() => {
    setCheckOut(addDays(checkIn, 2))
  }, [checkIn])

  useEffect(() => {
    const searchSuggestion = suggestPrices(searchBase, bucket)
    const packageSuggestion = suggestPrices(packageBase, bucket)
    setSearchExpPrice(searchSuggestion.exp)
    setSearchHbsPrice(searchSuggestion.hbs)
    setPackageExpPrice(packageSuggestion.exp)
    setPackageHbsPrice(packageSuggestion.hbs)
  }, [bucket, packageBase, searchBase])

  useEffect(() => {
    if (!searchAnchors.length) return
    setSelectedSearchId((current) => current || searchAnchors[0].atg_id)
  }, [searchAnchors])

  useEffect(() => {
    if (!packagesAnchors.length) return
    const firstHotel = packagesAnchors[0]
    setSelectedPackageHotelId((current) => current || firstHotel.atg_id)
  }, [packagesAnchors])

  useEffect(() => {
    if (packagesAnchors.length > 0) {
      setShowPackageAnchors(false)
    }
  }, [packagesAnchors.length])

  useEffect(() => {
    const offers = selectedPackageHotel?.data ?? []
    if (!offers.length) return
    setSelectedOfferId((current) => {
      if (current && offers.some((offer) => offer.room_id === current)) return current
      return pickDefaultOfferId(selectedPackageHotel)
    })
  }, [selectedPackageHotel])

  const fetchSearchAnchors = async () => {
    setFormError(null)
    if (!parsedHotelIds.length) {
      setFormError('Add at least one ATG hotel id')
      return
    }
    setSearchLoading(true)
    try {
      const result = await fetchCrawlaSearchAnchor({
        check_in: checkIn,
        check_out: checkOut,
        atg_hotel_ids: parsedHotelIds,
      })
      setSearchRawResponse(result)
      setShowSearchRaw(false)
      setSearchAnchors(result.data)
      if (result.data.length > 0) {
        setSelectedSearchId(result.data[0].atg_id)
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to fetch Crawla search anchors')
    } finally {
      setSearchLoading(false)
    }
  }

  const fetchPackageAnchors = async () => {
    setFormError(null)
    if (!parsedHotelIds.length) {
      setFormError('Add at least one ATG hotel id')
      return
    }
    setPackagesLoading(true)
    try {
      const result = await fetchCrawlaPackagesAnchor({
        check_in: checkIn,
        check_out: checkOut,
        atg_hotel_ids: parsedHotelIds,
      })
      setPackagesRawResponse(result)
      setShowPackagesRaw(false)
      setPackagesAnchors(result.hotels)
      if (result.hotels.length > 0) {
        setSelectedPackageHotelId(result.hotels[0].atg_id)
        setSelectedOfferId(pickDefaultOfferId(result.hotels[0]))
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to fetch Crawla package anchors')
    } finally {
      setPackagesLoading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError(null)
    if (!selectedSearch || !selectedPackageHotel || !selectedOffer) {
      setFormError('Fetch anchors and select a package offer first')
      return
    }

    const atgHotelId = selectedPackageHotel.atg_id || selectedSearch.atg_id || parsedHotelIds[0]
    if (!atgHotelId) {
      setFormError('Missing ATG hotel id')
      return
    }

    const rawRoomBasis = selectedOffer.room_basis ?? selectedOffer.meal ?? 'RO'
    // CHEAPEST_L2_GROSS: hardcode RO for both HBS and EXP.
    // Enigma requires RO for L2 eligibility. EXP room_name will be set to
    // "<crawla_room_name> L2" by the backend so HBS and EXP land in different
    // similar-package groups, allowing L2 to fire independently.
    const effectiveRoomBasis = bucket === 'CHEAPEST_L2_GROSS' ? 'RO' : rawRoomBasis

    const request: CrawlaScenarioRequest = {
      namespace: namespace.trim(),
      check_in: checkIn,
      check_out: checkOut,
      atg_hotel_id: atgHotelId,
      bucket,
      search: {
        crawla_total: selectedSearch.total_amount ?? selectedSearch.min_price ?? 0,
        exp_mode: bucket === 'ONLY_CRAWLA' ? 'EXCLUDE_HOTEL' : 'INCLUDE_HOTEL',
        exp_price: searchExpPrice,
        hbs_price: searchHbsPrice,
      },
      packages: {
        crawla_total: selectedOffer.total_amount,
        package_count: packageCount,
        package_price_mode: packagePriceMode,
        package_price_step: packagePriceStep,
        crawla_room_id: selectedOffer.room_id,
        crawla_room_name: selectedOffer.room_name,
        room_basis: effectiveRoomBasis,
        meal: selectedOffer.meal ?? effectiveRoomBasis,
        refundability: selectedOffer.refundability ?? 'NO',
        bed_type: selectedOffer.bed_type ?? null,
        exp_mode: bucket === 'ONLY_CRAWLA' ? 'EXCLUDE_HOTEL' : 'INCLUDE_HOTEL',
        exp_price: packageExpPrice,
        hbs_price: packageHbsPrice,
      },
    }

    await onSubmit(request)
  }

  return (
    <form className="wizard" onSubmit={handleSubmit}>
      <div className="wizard-section">
        <div className="wizard-section-title">Identity</div>
        <div className="field-row">
          <div className="field">
            <label>
              Namespace
              <input value={namespace} onChange={(e) => setNamespace(e.target.value)} required />
            </label>
          </div>
          <button type="button" className="btn ghost" onClick={() => setNamespace(defaultNamespace())}>
            ↻ New
          </button>
        </div>
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Stay & hotels</div>
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
              <input type="date" value={checkOut} readOnly required />
            </label>
            <p className="hint" style={{ marginTop: '0.35rem' }}>
              Crawla requires checkout to be exactly 2 calendar days after check-in.
            </p>
          </div>
          <div className="field field-wide">
            <label>
              ATG hotel ids
              <textarea
                rows={3}
                value={hotelIdsText}
                onChange={(e) => setHotelIdsText(e.target.value)}
                placeholder="1446194, 1057823"
              />
            </label>
          </div>
        </div>
        <div className="field-row" style={{ marginTop: '0.75rem' }}>
          <button type="button" className="btn secondary" onClick={fetchSearchAnchors} disabled={searchLoading}>
            {searchLoading ? 'Fetching search…' : 'Fetch search anchor'}
          </button>
          <button type="button" className="btn secondary" onClick={fetchPackageAnchors} disabled={packagesLoading}>
            {packagesLoading ? 'Fetching packages…' : 'Fetch package anchor'}
          </button>
        </div>
        {searchRawResponse != null && (
          <div className="result-disclosure" style={{ marginTop: '0.75rem' }}>
            <button
              type="button"
              className="btn ghost result-disclosure-toggle"
              onClick={() => setShowSearchRaw((v) => !v)}
              aria-expanded={showSearchRaw}
            >
              <span className={`result-disclosure-arrow ${showSearchRaw ? 'open' : ''}`}>▾</span>
              {showSearchRaw ? 'Hide search response' : 'Show search response'}
            </button>
            {showSearchRaw && (
              <pre className="raw-response">{JSON.stringify(searchRawResponse, null, 2)}</pre>
            )}
          </div>
        )}
        {packagesRawResponse != null && (
          <div className="result-disclosure" style={{ marginTop: '0.5rem' }}>
            <button
              type="button"
              className="btn ghost result-disclosure-toggle"
              onClick={() => setShowPackagesRaw((v) => !v)}
              aria-expanded={showPackagesRaw}
            >
              <span className={`result-disclosure-arrow ${showPackagesRaw ? 'open' : ''}`}>▾</span>
              {showPackagesRaw ? 'Hide packages response' : 'Show packages response'}
            </button>
            {showPackagesRaw && (
              <pre className="raw-response">{JSON.stringify(packagesRawResponse, null, 2)}</pre>
            )}
          </div>
        )}
      </div>

      <div className="wizard-section">
        <div className="wizard-section-title">Bucket</div>
        <div className="field">
          <label>
            Bucket
            <select value={bucket} onChange={(e) => setBucket(e.target.value as CrawlaBucket)}>
              <option value="CRAWLA_LOWER">CRAWLA_LOWER</option>
              <option value="EXPEDIA_LOWER">EXPEDIA_LOWER</option>
              <option value="EQUAL">EQUAL</option>
              <option value="ONLY_EXPEDIA">ONLY_EXPEDIA</option>
              <option value="ONLY_CRAWLA">ONLY_CRAWLA</option>
              <option value="CHEAPEST_L2_GROSS">CHEAPEST_L2_GROSS</option>
            </select>
          </label>
        </div>
      </div>

      {searchAnchors.length > 0 && (
        <div className="wizard-section">
          <div className="wizard-section-title">Search anchors</div>
          {selectedSearch && (
            <div className="field" style={{ marginBottom: '0.85rem' }}>
              <label>
                Selected search details
                <input
                  readOnly
                  value={`${selectedSearch.room_name ?? 'Room n/a'} | basis ${selectedSearch.room_basis ?? 'RO'} | ${formatMoney(selectedSearch.total_amount ?? selectedSearch.min_price)} | ${selectedSearch.atg_id}`}
                />
              </label>
            </div>
          )}
          <div className="anchor-grid">
            {searchAnchors.map((item) => (
              <button
                key={item.atg_id}
                type="button"
                className={selectedSearchId === item.atg_id ? 'anchor-card active' : 'anchor-card'}
                onClick={() => setSelectedSearchId(item.atg_id)}
              >
                <strong>{item.atg_id}</strong>
                <span>min {formatMoney(item.min_price)}</span>
                <span>{searchLabel(item)}</span>
                <span>{item.currency ?? 'SAR'}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {packagesAnchors.length > 0 && (
        <div className="wizard-section">
          <div className="result-disclosure" style={{ marginTop: 0 }}>
            <button
              type="button"
              className="btn ghost result-disclosure-toggle"
              onClick={() => setShowPackageAnchors((current) => !current)}
              aria-expanded={showPackageAnchors}
            >
              <span className={`result-disclosure-arrow ${showPackageAnchors ? 'open' : ''}`}>▾</span>
              {showPackageAnchors ? 'Hide package anchors' : 'Show package anchors'}
            </button>
          </div>

          {showPackageAnchors && (
            <>
              <div className="wizard-section-title">Package anchors</div>
              <div className="field" style={{ marginBottom: '0.85rem' }}>
                <label>
                  Package offer to mock
                  <select
                    value={selectedOfferId}
                    onChange={(e) => {
                      setSelectedOfferId(e.target.value)
                    }}
                  >
                    {selectedPackageHotel?.data?.map((offer) => (
                      <option key={offer.room_id} value={offer.room_id}>
                        {offerLabel(offer)}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="hint" style={{ marginTop: '0.35rem' }}>
                  This row becomes the Crawla package template used for HBS mock generation.
                </p>
              </div>
              {selectedOffer && (
                <div className="field" style={{ marginBottom: '0.85rem' }}>
                  <label>
                    Selected offer details
                    <input
                      readOnly
                      value={`${selectedOffer.room_name} | basis ${selectedOffer.room_basis ?? selectedOffer.meal ?? 'RO'} | refund ${selectedOffer.refundability ?? 'NO'} | ${formatMoney(selectedOffer.total_amount)} | ${selectedOffer.room_id}`}
                    />
                  </label>
                </div>
              )}
              <div className="anchor-list">
                {packagesAnchors.map((hotel) => (
                  <div key={hotel.atg_id} className="anchor-hotel">
                    <div className="anchor-hotel-head">
                      <button
                        type="button"
                        className={selectedPackageHotelId === hotel.atg_id ? 'btn tiny secondary' : 'btn tiny ghost'}
                        onClick={() => {
                          setSelectedPackageHotelId(hotel.atg_id)
                          const first = hotel.data[0]
                          if (first) setSelectedOfferId(first.room_id)
                        }}
                      >
                        Use {hotel.atg_id}
                      </button>
                      <button
                        type="button"
                        className="btn tiny ghost"
                        onClick={() => {
                          setSelectedPackageHotelId(hotel.atg_id)
                          setSelectedOfferId(pickDefaultOfferId(hotel))
                        }}
                      >
                        Mock min-price row
                      </button>
                      <span className="hint">
                        min {formatMoney(hotel.min_price)} · {hotel.status ?? 'n/a'}{' '}
                        {selectedPackageHotelId === hotel.atg_id && selectedOfferId ? '· active hotel' : ''}
                      </span>
                    </div>
                    <div className="offer-table">
                      {hotel.data.map((offer) => (
                        <button
                          key={offer.room_id}
                          type="button"
                          className={selectedOfferId === offer.room_id ? 'offer-row active' : 'offer-row'}
                          onClick={() => {
                            setSelectedPackageHotelId(hotel.atg_id)
                            setSelectedOfferId(offer.room_id)
                          }}
                        >
                          <strong>{offer.room_name}</strong>
                          <span>{offer.room_id}</span>
                          <span>{offer.room_basis ?? offer.meal ?? 'RO'}</span>
                          <span>{offer.refundability ?? 'NO'}</span>
                          <span>{formatMoney(offer.total_amount)}</span>
                          {selectedOfferId === offer.room_id && (
                            <span className="pill" style={{ marginLeft: 'auto' }}>
                              Selected
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      <div className="wizard-section">
        <div className="wizard-section-title">Prices</div>
        <div className="field-grid">
          <div className="field">
            <label>
              Search Crawla
              <input value={formatMoney(searchBase)} readOnly />
            </label>
          </div>
          <div className="field">
            <label>
              Search EXP
              <input
                type="number"
                value={searchExpPrice}
                onChange={(e) => setSearchExpPrice(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Search HBS
              <input
                type="number"
                value={searchHbsPrice}
                onChange={(e) => setSearchHbsPrice(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Package Crawla
              <input value={formatMoney(packageBase)} readOnly />
            </label>
          </div>
          <div className="field">
            <label>
              Package EXP
              <input
                type="number"
                value={packageExpPrice}
                onChange={(e) => setPackageExpPrice(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Package HBS
              <input
                type="number"
                value={packageHbsPrice}
                onChange={(e) => setPackageHbsPrice(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Package count
              <input
                type="number"
                min={1}
                max={20}
                value={packageCount}
                onChange={(e) => setPackageCount(Math.max(1, Number(e.target.value) || 1))}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Package price mode
              <select value={packagePriceMode} onChange={(e) => setPackagePriceMode(e.target.value as CrawlaPackagePriceMode)}>
                <option value="SAME">Same</option>
                <option value="INCREASE">Higher</option>
                <option value="DECREASE">Lower</option>
              </select>
            </label>
          </div>
          <div className="field">
            <label>
              Package price step
              <input
                type="number"
                min={0}
                step="0.01"
                value={packagePriceStep}
                onChange={(e) => setPackagePriceStep(Math.max(0, Number(e.target.value) || 0))}
              />
            </label>
            <p className="hint" style={{ marginTop: '0.35rem' }}>
              Used when the mode is Higher or Lower.
            </p>
          </div>
        </div>
        <div className="result-disclosure" style={{ marginTop: '0.9rem' }}>
          <button
            type="button"
            className="btn ghost result-disclosure-toggle"
            onClick={() => setShowPackagePreview((current) => !current)}
            aria-expanded={showPackagePreview}
          >
            <span className={`result-disclosure-arrow ${showPackagePreview ? 'open' : ''}`}>▾</span>
            {showPackagePreview ? 'Hide package preview' : 'Show package preview'}
          </button>
        </div>
        {showPackagePreview && (
          <div className="list-panel" style={{ marginTop: 0.5 }}>
            <div className="data-section-title">Generated package preview</div>
            <div className="meta-grid">
              <div className="meta-item">
                <span>HBS</span>
                <strong>{packageHbsSeries.join(' · ')}</strong>
              </div>
              <div className="meta-item">
                <span>EXP</span>
                <strong>{packageExpSeries.join(' · ')}</strong>
              </div>
            </div>
          </div>
        )}
      </div>

      {formError && <p className="error-text">{formError}</p>}

      <div className="wizard-actions">
        <button type="submit" className="btn" disabled={busy}>
          {busy ? 'Creating…' : 'Create Crawla scenario'}
        </button>
      </div>
    </form>
  )
}
