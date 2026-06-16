/**
 * CrawlaQueueRunner — sequential execution of all Crawla bucket scenarios.
 *
 * Isolated from CrawlaMocksWizard. Reuses existing API functions:
 *   createCrawlaScenario, runCrawlaScenario  (crawla.ts)
 *   getScenario, teardownScenario            (scenarios.ts)
 *   fetchCrawlaSearchAnchor, fetchCrawlaPackagesAnchor (crawla.ts)
 *
 * Execution order per bucket:
 *   1. Create scenario  → POST /api/crawla/scenarios
 *   2. Poll until READY → GET  /api/scenarios/{id}
 *   3. Run scenario     → POST /api/crawla/scenarios/{id}/run
 *   4. Teardown         → DELETE /api/scenarios/{id}
 *   5. Poll until TORN_DOWN (cleanup verification)
 *   6. Proceed to next bucket
 */

import { useRef, useState } from 'react'
import {
  createCrawlaScenario,
  fetchCrawlaPackagesAnchor,
  fetchCrawlaSearchAnchor,
  runCrawlaScenario,
} from '../api/crawla'
import { getScenario, teardownScenario } from '../api/scenarios'
import type {
  CrawlaAnchorPackagesResponse,
  CrawlaAnchorSearchResponse,
  CrawlaBucket,
  CrawlaScenarioRequest,
  CrawlaScenarioRunResult,
} from '../types/crawla'
import type { ScenarioBundle } from '../types/scenario'

// ─── Constants ───────────────────────────────────────────────────────────────

const POLL_INTERVAL_MS = 2000
const MAX_POLL_READY = 90   // 3 minutes for scenario creation
const MAX_POLL_TORN = 30    // 1 minute for teardown verification

const BUCKET_ORDER: { bucket: CrawlaBucket; label: string }[] = [
  { bucket: 'CRAWLA_LOWER',      label: 'Crawla Lower'      },
  { bucket: 'EXPEDIA_LOWER',     label: 'Expedia Lower'     },
  { bucket: 'EQUAL',             label: 'Equal'             },
  { bucket: 'ONLY_EXPEDIA',      label: 'Only Expedia'      },
  { bucket: 'ONLY_CRAWLA',       label: 'Only Crawla'       },
  { bucket: 'CHEAPEST_L2_GROSS', label: 'Cheapest L2 Gross' },
]

// ─── Types ───────────────────────────────────────────────────────────────────

type BucketStatus = 'pending' | 'running' | 'completed' | 'failed'

type RunPhase =
  | 'fetching_anchors'
  | 'creating'
  | 'waiting_ready'
  | 'running_scenario'
  | 'tearing_down'
  | 'verifying_cleanup'

interface BucketItem {
  bucket: CrawlaBucket
  label: string
  status: BucketStatus
  phase?: RunPhase
  scenarioId?: string
  bundle?: ScenarioBundle
  runResult?: CrawlaScenarioRunResult
  error?: string
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatLocalDate(date: Date): string {
  const y = date.getFullYear()
  const m = `${date.getMonth() + 1}`.padStart(2, '0')
  const d = `${date.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${d}`
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(`${dateStr}T00:00:00`)
  d.setDate(d.getDate() + days)
  return formatLocalDate(d)
}

function defaultCheckIn(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return formatLocalDate(d)
}

function defaultNamespace(bucket: CrawlaBucket): string {
  const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
  const suffix = Math.random().toString(36).slice(2, 6)
  return `queue-${bucket.toLowerCase().replace(/_/g, '-')}-${stamp}-${suffix}`
}

function suggestPrices(base: number, bucket: CrawlaBucket): { exp: number; hbs: number } {
  if (bucket === 'ONLY_CRAWLA') return { exp: 0, hbs: Number((base * 1.1).toFixed(2)) }

  const expFactors: Record<CrawlaBucket, number> = {
    CRAWLA_LOWER:      1.15,
    EXPEDIA_LOWER:     0.85,
    EQUAL:             1.00,
    ONLY_EXPEDIA:      1.00,
    ONLY_CRAWLA:       1.00,
    CHEAPEST_L2_GROSS: 0.85,
  }

  const exp = bucket === 'ONLY_EXPEDIA'
    ? 500
    : Number((base * expFactors[bucket]).toFixed(2))

  const hbs = Number((exp * 0.35).toFixed(2))
  return { exp, hbs }
}

function buildRequest(
  bucket: CrawlaBucket,
  atgHotelId: string,
  checkIn: string,
  checkOut: string,
  searchAnchors: CrawlaAnchorSearchResponse,
  packagesAnchors: CrawlaAnchorPackagesResponse,
): CrawlaScenarioRequest {
  const searchItem = searchAnchors.data.find((i) => i.atg_id === atgHotelId) ?? searchAnchors.data[0]
  const hotelItem  = packagesAnchors.hotels.find((h) => h.atg_id === atgHotelId) ?? packagesAnchors.hotels[0]
  const offer      = hotelItem?.data[0]

  const searchBase  = searchItem?.total_amount ?? searchItem?.min_price ?? 500
  const packageBase = offer?.total_amount ?? hotelItem?.min_price ?? searchBase

  const searchPrices  = suggestPrices(searchBase,  bucket)
  const packagePrices = suggestPrices(packageBase, bucket)

  const expMode = bucket === 'ONLY_CRAWLA' ? 'EXCLUDE_HOTEL' : 'INCLUDE_HOTEL'

  // CHEAPEST_L2_GROSS room-basis: hardcode RO for both HBS and EXP.
  const rawRoomBasis = offer?.room_basis ?? offer?.meal ?? 'RO'
  const effectiveRoomBasis = bucket === 'CHEAPEST_L2_GROSS' ? 'RO' : rawRoomBasis
  const effectiveRefundability = offer?.refundability ?? 'NO'

  return {
    namespace:    defaultNamespace(bucket),
    check_in:     checkIn,
    check_out:    checkOut,
    atg_hotel_id: atgHotelId,
    bucket,
    search: {
      crawla_total: searchBase,
      exp_mode:     expMode,
      exp_price:    searchPrices.exp,
      hbs_price:    searchPrices.hbs,
    },
    packages: {
      crawla_total:        packageBase,
      exp_mode:            expMode,
      exp_price:           packagePrices.exp,
      hbs_price:           packagePrices.hbs,
      package_count:       1,
      package_price_mode:  'SAME',
      package_price_step:  0,
      crawla_room_id:   offer?.room_id   ?? 'default-room',
      crawla_room_name: offer?.room_name ?? 'Room',
      room_basis:   effectiveRoomBasis,
      meal:         offer?.meal ?? effectiveRoomBasis,
      refundability: effectiveRefundability,
      bed_type:     offer?.bed_type ?? null,
    },
  }
}

async function pollUntilStatus(
  scenarioId: string,
  targets: string[],
  maxAttempts: number,
  notFoundMeansSuccess = false,
): Promise<ScenarioBundle> {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const data = await getScenario(scenarioId)
      if (targets.includes(data.status)) return data
      if (data.status === 'FAILED') throw new Error(data.error_message || 'Scenario failed')
    } catch (err) {
      if (notFoundMeansSuccess) {
        const msg = err instanceof Error ? err.message.toLowerCase() : ''
        if (msg.includes('not found') || msg.includes('404')) {
          return { id: scenarioId, status: 'TORN_DOWN' } as unknown as ScenarioBundle
        }
      }
      throw err
    }
    await new Promise<void>((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  throw new Error(`Timed out waiting for scenario ${scenarioId} (targets: ${targets.join(', ')})`)
}

function phaseLabel(phase: RunPhase): string {
  switch (phase) {
    case 'fetching_anchors':   return 'Fetching Crawla anchors…'
    case 'creating':           return 'Creating scenario…'
    case 'waiting_ready':      return 'Waiting for mocks to be ready…'
    case 'running_scenario':   return 'Running Crawla scenario…'
    case 'tearing_down':       return 'Clearing mock data…'
    case 'verifying_cleanup':  return 'Verifying cleanup…'
  }
}

function statusLabel(status: BucketStatus): string {
  switch (status) {
    case 'pending':   return 'Pending'
    case 'running':   return 'Running'
    case 'completed': return 'Completed'
    case 'failed':    return 'Failed'
  }
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button type="button" className="btn tiny ghost" onClick={copy}>
      {copied ? '✓' : 'Copy'}
    </button>
  )
}

function QueueRow({ item, index }: { item: BucketItem; index: number }) {
  const [expanded, setExpanded] = useState(false)
  const hasDetails = Boolean(item.scenarioId || item.bundle || item.runResult || item.error)

  return (
    <div className={`qr-item qr-item--${item.status}`}>
      <div className="qr-item-header">
        <span className="qr-item-num">{index + 1}</span>
        <span className="qr-item-label">{item.label}</span>

        <span className={`qr-pill qr-pill--${item.status}`}>
          {item.status === 'running' && <span className="pulse-dot" style={{ width: 7, height: 7 }} />}
          {statusLabel(item.status)}
        </span>

        {item.phase && item.status === 'running' && (
          <span className="qr-phase">{phaseLabel(item.phase)}</span>
        )}

        {item.runResult?.search_s_id && (
          <span className="qr-sid-inline">
            <span className="qr-sid-label">SID</span>
            <code className="qr-sid-value">{item.runResult.search_s_id}</code>
            <CopyButton value={item.runResult.search_s_id} />
          </span>
        )}

        {hasDetails && (
          <button
            type="button"
            className="btn tiny ghost"
            onClick={() => setExpanded((v) => !v)}
            style={{ marginLeft: 'auto' }}
          >
            {expanded ? '▴ Hide' : '▾ Details'}
          </button>
        )}
      </div>

      {expanded && (
        <div className="qr-item-body">
          {item.runResult?.search_s_id && (
            <div className="qr-meta-row qr-meta-row--highlight">
              <span>Search SID</span>
              <code>{item.runResult.search_s_id}</code>
              <CopyButton value={item.runResult.search_s_id} />
            </div>
          )}
          {item.scenarioId && (
            <div className="qr-meta-row">
              <span>Scenario ID</span>
              <code>{item.scenarioId}</code>
              <CopyButton value={item.scenarioId} />
            </div>
          )}
          {item.bundle?.namespace && (
            <div className="qr-meta-row">
              <span>Namespace</span>
              <code>{item.bundle.namespace}</code>
              <CopyButton value={item.bundle.namespace} />
            </div>
          )}
          {item.bundle?.api_key && (
            <div className="qr-meta-row">
              <span>API key</span>
              <code>{item.bundle.api_key}</code>
              <CopyButton value={item.bundle.api_key} />
            </div>
          )}
          {item.bundle?.contracts && Object.keys(item.bundle.contracts).length > 0 && (
            Object.entries(item.bundle.contracts).map(([supplier, contractId]) => (
              <div key={supplier} className="qr-meta-row">
                <span>{supplier} contract</span>
                <code>{contractId}</code>
                <CopyButton value={contractId} />
              </div>
            ))
          )}
          {item.bundle?.booking_ids && Object.keys(item.bundle.booking_ids).length > 0 && (
            Object.entries(item.bundle.booking_ids).map(([supplier, bid]) => (
              <div key={supplier} className="qr-meta-row">
                <span>{supplier} booking ID</span>
                <code>{bid}</code>
                <CopyButton value={bid} />
              </div>
            ))
          )}
          {item.runResult && (
            <>
              <div className="qr-section-title">Run result</div>
              <div className="qr-meta-row">
                <span>Search SID</span>
                <code>{item.runResult.search_s_id}</code>
                <CopyButton value={item.runResult.search_s_id} />
              </div>
              <div className="qr-meta-row">
                <span>Search status</span>
                <code>{item.runResult.search_status}</code>
              </div>
              <div className="qr-meta-row">
                <span>Package status</span>
                <code>{item.runResult.package_status}</code>
              </div>
              {item.runResult.error_message && (
                <div className="qr-meta-row qr-meta-row--error">
                  <span>Run error</span>
                  <code>{item.runResult.error_message}</code>
                </div>
              )}
              {item.runResult.logs.length > 0 && (
                <div className="qr-logs">
                  {item.runResult.logs.map((log, i) => (
                    <div key={i} className="qr-log-row">
                      <span className={`qr-log-status qr-log-status--${log.status?.toLowerCase()}`}>
                        {log.status}
                      </span>
                      <span className="qr-log-step">{log.step}</span>
                      <code className="qr-log-path">{log.method} {log.path}</code>
                      <span className="qr-log-http">{log.http_status}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
          {item.bundle?.status === 'TORN_DOWN' && !item.error && (
            <div className="qr-cleanup-ok">✓ Mock data verified cleared</div>
          )}
          {item.error && (
            <div className="qr-error-detail">{item.error}</div>
          )}
        </div>
      )}
    </div>
  )
}

export function CrawlaQueueRunner() {
  const initialCheckIn = defaultCheckIn()

  const [atgHotelId, setAtgHotelId] = useState('1043546')
  const [checkIn,    setCheckIn]    = useState(initialCheckIn)
  const [checkOut,   setCheckOut]   = useState(() => addDays(initialCheckIn, 2))

  const [items, setItems] = useState<BucketItem[]>(
    BUCKET_ORDER.map(({ bucket, label }) => ({ bucket, label, status: 'pending' })),
  )
  const [running,  setRunning]  = useState(false)
  const [aborted,  setAborted]  = useState(false)
  const [globalErr, setGlobalErr] = useState<string | null>(null)

  const abortRef = useRef(false)

  const patchItem = (bucket: CrawlaBucket, patch: Partial<BucketItem>) => {
    setItems((prev) =>
      prev.map((item) => (item.bucket === bucket ? { ...item, ...patch } : item)),
    )
  }

  const resetAll = () => {
    abortRef.current = false
    setAborted(false)
    setGlobalErr(null)
    setItems(BUCKET_ORDER.map(({ bucket, label }) => ({ bucket, label, status: 'pending' })))
  }

  const handleStop = () => {
    abortRef.current = true
    setAborted(true)
  }

  const runAll = async () => {
    if (!atgHotelId.trim()) return

    abortRef.current = false
    setAborted(false)
    setGlobalErr(null)
    setRunning(true)
    setItems(BUCKET_ORDER.map(({ bucket, label }) => ({ bucket, label, status: 'pending' })))

    patchItem('CRAWLA_LOWER', { status: 'running', phase: 'fetching_anchors' })

    let searchAnchors: CrawlaAnchorSearchResponse  = { data: [] }
    let packagesAnchors: CrawlaAnchorPackagesResponse = { hotels: [] }

    try {
      const payload = { check_in: checkIn, check_out: checkOut, atg_hotel_ids: [atgHotelId] }
      ;[searchAnchors, packagesAnchors] = await Promise.all([
        fetchCrawlaSearchAnchor(payload),
        fetchCrawlaPackagesAnchor(payload),
      ])
    } catch {
      // Non-fatal — ONLY_EXPEDIA doesn't need real anchor data.
    }

    patchItem('CRAWLA_LOWER', { status: 'pending', phase: undefined })

    for (const { bucket } of BUCKET_ORDER) {
      if (abortRef.current) break

      patchItem(bucket, { status: 'running', phase: 'creating', error: undefined })

      try {
        const today = formatLocalDate(new Date())
        const effectiveCheckIn  = bucket === 'ONLY_EXPEDIA' ? addDays(today, 14) : checkIn
        const effectiveCheckOut = bucket === 'ONLY_EXPEDIA' ? addDays(effectiveCheckIn, 2) : checkOut

        const request = buildRequest(bucket, atgHotelId, effectiveCheckIn, effectiveCheckOut, searchAnchors, packagesAnchors)
        const created = await createCrawlaScenario(request)
        if (!created.id) throw new Error('Create response missing scenario id')
        const scenarioId = created.id
        patchItem(bucket, { scenarioId, phase: 'waiting_ready' })

        if (abortRef.current) break

        const readyBundle = await pollUntilStatus(scenarioId, ['READY'], MAX_POLL_READY)
        patchItem(bucket, { bundle: readyBundle, phase: 'running_scenario' })

        if (abortRef.current) break

        const runResult = await runCrawlaScenario(scenarioId)
        patchItem(bucket, { runResult, phase: 'tearing_down' })

        if (abortRef.current) break

        await teardownScenario(scenarioId)
        patchItem(bucket, { phase: 'verifying_cleanup' })

        try {
          const tornBundle = await pollUntilStatus(scenarioId, ['TORN_DOWN'], MAX_POLL_TORN, true)
          patchItem(bucket, { bundle: tornBundle, status: 'completed', phase: undefined })
        } catch (teardownErr) {
          const msg = teardownErr instanceof Error ? teardownErr.message : String(teardownErr)
          const isTimeout = msg.toLowerCase().includes('timed out')
          patchItem(bucket, {
            status: 'completed',
            phase: undefined,
            error: isTimeout
              ? 'Teardown initiated but confirmation timed out — mock data will be cleaned up in background'
              : `Teardown verification warning: ${msg}`,
          })
        }

      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        patchItem(bucket, { status: 'failed', error: message, phase: undefined })
      }
    }

    setRunning(false)
  }

  const completedCount   = items.filter((i) => i.status === 'completed').length
  const failedCount      = items.filter((i) => i.status === 'failed').length
  const currentlyRunning = items.find((i) => i.status === 'running')
  const allSettled       = completedCount + failedCount === BUCKET_ORDER.length
  const showReset        = allSettled || (aborted && !running)
  const progressPct      = Math.round((completedCount / BUCKET_ORDER.length) * 100)

  return (
    <div className="qr-root">
      <div className="wizard-section">
        <div className="wizard-section-title">Queue parameters</div>
        <div className="field-grid">
          <div className="field">
            <label>
              ATG hotel ID
              <input
                value={atgHotelId}
                onChange={(e) => setAtgHotelId(e.target.value.trim())}
                disabled={running}
                placeholder="e.g. 1043546"
              />
            </label>
          </div>
          <div className="field">
            <label>
              Check-in
              <input
                type="date"
                value={checkIn}
                disabled={running}
                onChange={(e) => {
                  setCheckIn(e.target.value)
                  setCheckOut(addDays(e.target.value, 2))
                }}
              />
            </label>
          </div>
          <div className="field">
            <label>
              Check-out
              <input
                type="date"
                value={checkOut}
                disabled={running}
                onChange={(e) => setCheckOut(e.target.value)}
              />
            </label>
          </div>
        </div>
        <p className="hint" style={{ marginTop: '0.5rem' }}>
          Prices are auto-derived from live Crawla anchors using bucket formulas.
          Currency fixed to SAR · 1 room · 2 adults · 0 kids.
        </p>
      </div>

      <div className="qr-actions">
        {!running && !showReset && (
          <button
            type="button"
            className="btn"
            onClick={runAll}
            disabled={!atgHotelId.trim()}
          >
            ▶ Run All Scenarios
          </button>
        )}
        {running && (
          <button type="button" className="btn danger" onClick={handleStop}>
            ■ Stop
          </button>
        )}
        {showReset && (
          <>
            {!running && (
              <button type="button" className="btn" onClick={runAll} disabled={!atgHotelId.trim()}>
                ▶ Run All Scenarios
              </button>
            )}
            <button type="button" className="btn ghost" onClick={resetAll}>
              ↺ Reset queue
            </button>
          </>
        )}
      </div>

      {globalErr && <div className="banner error"><span>⚠</span><span>{globalErr}</span></div>}

      {(running || allSettled || aborted) && (
        <div className="qr-overall">
          <div className="qr-overall-bar">
            <div className="qr-overall-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="qr-overall-stats">
            <span>{completedCount} / {BUCKET_ORDER.length} completed</span>
            {failedCount > 0 && <span className="qr-stat-fail">{failedCount} failed</span>}
            {aborted && !running && <span className="qr-stat-warn">Stopped by user</span>}
            {allSettled && failedCount === 0 && (
              <span className="qr-stat-ok">All scenarios completed successfully</span>
            )}
          </div>
          {currentlyRunning && (
            <div className="qr-running-banner">
              <span className="pulse-dot" />
              Running <strong>{currentlyRunning.label}</strong>
              {currentlyRunning.phase && (
                <span className="qr-running-phase"> — {phaseLabel(currentlyRunning.phase)}</span>
              )}
            </div>
          )}
        </div>
      )}

      <div className="qr-list">
        {items.map((item, index) => (
          <QueueRow key={item.bucket} item={item} index={index} />
        ))}
      </div>
    </div>
  )
}
