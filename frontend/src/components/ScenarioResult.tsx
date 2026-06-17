import { useEffect, useState } from 'react'
import type { CrawlaScenarioRunResult } from '../types/crawla'
import type { ScenarioBundle } from '../types/scenario'

interface Props {
  bundle: ScenarioBundle
  onRefreshBookingIds?: () => void
  onTeardown?: () => void
  onRunCrawlaScenario?: () => Promise<void>
  onToggleLogs?: () => void
  crawlaRunResult?: CrawlaScenarioRunResult | null
  showLogs?: boolean
  actionBusy?: boolean
  runBusy?: boolean
}

function CopyRow({
  label,
  value,
  stacked = false,
}: {
  label: string
  value: string
  stacked?: boolean
}) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={stacked ? 'copy-row stacked' : 'copy-row'}>
      <span className="copy-label">{label}</span>
      <code className="copy-value">{value}</code>
      <button type="button" className="btn tiny ghost" onClick={copy}>
        {copied ? '✓' : 'Copy'}
      </button>
    </div>
  )
}

function CopyJson({ label, value }: { label: string; value: Record<string, unknown> }) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(JSON.stringify(value, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="json-panel">
      <div className="json-panel-head">
        <span className="copy-label">{label}</span>
        <button type="button" className="btn tiny ghost" onClick={copy}>
          {copied ? '✓' : 'Copy JSON'}
        </button>
      </div>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  )
}

export function ScenarioResult({
  bundle,
  onRefreshBookingIds,
  onTeardown,
  onRunCrawlaScenario,
  onToggleLogs,
  crawlaRunResult,
  showLogs,
  actionBusy,
  runBusy,
}: Props) {
  const [showCredentials, setShowCredentials] = useState(false)
  const [showScenarioInfo, setShowScenarioInfo] = useState(false)
  const [showRunDetails, setShowRunDetails] = useState(false)

  useEffect(() => {
    setShowCredentials(false)
    setShowScenarioInfo(false)
    setShowRunDetails(false)
  }, [bundle.namespace, bundle.status])

  useEffect(() => {
    if (showLogs) {
      setShowRunDetails(true)
    }
  }, [showLogs])

  useEffect(() => {
    if (crawlaRunResult) {
      setShowRunDetails(true)
    }
  }, [crawlaRunResult])

  if (bundle.status === 'FAILED') {
    return (
      <div className="result-panel">
        <div className="error-box">
          <h3>Scenario failed</h3>
          <p>{bundle.error_message ?? 'Unknown error occurred during provisioning.'}</p>
        </div>
      </div>
    )
  }

  if (bundle.status !== 'READY' && bundle.status !== 'TORN_DOWN') {
    return null
  }

  const torn = bundle.status === 'TORN_DOWN'
  const brSetupFailed = bundle.br_setup?.status === 'FAILED'

  return (
    <div className="result-panel">
      <div className={`success-banner ${torn ? 'torn' : ''}`}>
        <div className="success-icon">{torn ? '○' : '✓'}</div>
        <div>
          <h3>{torn ? 'Scenario torn down' : 'Ready for QA'}</h3>
          <p>
            {torn
              ? 'MockServer expectations cleared for this namespace.'
              : 'Use the apiKey below in your Enigma search/booking flow.'}
          </p>
        </div>
      </div>

      {brSetupFailed && (
        <div className="error-box" style={{ marginTop: '1rem' }}>
          <h3>BR setup failed</h3>
          <p>{bundle.error_message ?? 'Mock creation completed, but Business Rule setup needs checking.'}</p>
        </div>
      )}

      {crawlaRunResult && (
        <>
          <div className="result-disclosure" style={{ marginTop: '1rem' }}>
            <button
              type="button"
              className="btn ghost result-disclosure-toggle"
              onClick={() => setShowRunDetails((current) => !current)}
              aria-expanded={showRunDetails}
            >
              <span className={`result-disclosure-arrow ${showRunDetails ? 'open' : ''}`}>▾</span>
              {showRunDetails ? 'Hide run details' : 'Show run details'}
            </button>
          </div>

          {showRunDetails && (
            <>
              <div className="data-section-title">Core run</div>
              {crawlaRunResult.error_message && (
                <div className="error-box" style={{ marginBottom: '1rem' }}>
                  <h3>Run failed</h3>
                  <p>{crawlaRunResult.error_message}</p>
                </div>
              )}
              <div className="data-grid">
                <CopyRow label="Search sId" value={crawlaRunResult.search_s_id} />
                <CopyRow label="Search status" value={crawlaRunResult.search_status} />
                <CopyRow label="Search hotel" value={crawlaRunResult.search_hotel_id} />
                <CopyRow label="Packages pId" value={crawlaRunResult.package_p_id} />
                <CopyRow label="Packages status" value={crawlaRunResult.package_status} />
              </div>
              {showLogs && (
                <>
                  <div className="data-section-title">SMF logs</div>
                  {crawlaRunResult.logs.length > 0 ? (
                    <div className="list-panel" style={{ marginTop: 0 }}>
                      <ul className="scenario-list">
                        {crawlaRunResult.logs.map((entry, index) => (
                          <li key={`${entry.step}-${entry.path}-${index}`}>
                            <div className="copy-row" style={{ alignItems: 'flex-start' }}>
                              <span className="copy-label">{entry.step}</span>
                              <code className="copy-value" style={{ whiteSpace: 'pre-wrap' }}>
                                {`${entry.method} ${entry.path} | attempt ${entry.attempt} | http ${entry.http_status} | status ${entry.status || 'n/a'}`}
                              </code>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <div className="error-box" style={{ marginTop: 0 }}>
                      <h3>No logs captured</h3>
                      <p>{crawlaRunResult.error_message ?? 'The run finished without collecting trace data.'}</p>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </>
      )}

      <div className="result-disclosure" style={{ marginTop: '1rem' }}>
        <button
          type="button"
          className="btn ghost result-disclosure-toggle"
          onClick={() => setShowScenarioInfo((current) => !current)}
          aria-expanded={showScenarioInfo}
        >
          <span className={`result-disclosure-arrow ${showScenarioInfo ? 'open' : ''}`}>▾</span>
          {showScenarioInfo ? 'Hide scenario info' : 'Show scenario info'}
        </button>
      </div>

      {showScenarioInfo && (
        <>
          <div className="data-section-title">Crawla export</div>
          {bundle.crawla_export && (
            <CopyJson label="Export payload" value={bundle.crawla_export as Record<string, unknown>} />
          )}

          <div className="data-section-title">Scenario info</div>
          <div className="meta-grid">
            <div className="meta-item">
              <span>Expectations</span>
              <strong>{bundle.expectation_count}</strong>
            </div>
            <div className="meta-item">
              <span>ATG hotel</span>
              <strong>{bundle.atg_hotel_id}</strong>
            </div>
            {bundle.supplier_hotel_ids && Object.keys(bundle.supplier_hotel_ids).length > 0 && (
              <div className="meta-item" style={{ gridColumn: '1 / -1' }}>
                <span>Supplier hotels</span>
                <strong>
                  {Object.entries(bundle.supplier_hotel_ids)
                    .map(([code, id]) => `${code}: ${id}`)
                    .join(' · ')}
                </strong>
              </div>
            )}
            <div className="meta-item">
              <span>Stay</span>
              <strong>
                {bundle.check_in} → {bundle.check_out}
              </strong>
            </div>
            <div className="meta-item">
              <span>Namespace</span>
              <strong>{bundle.namespace}</strong>
            </div>
            {bundle.mock_server_base_url && (
              <div className="meta-item" style={{ gridColumn: '1 / -1' }}>
                <span>MockServer</span>
                <strong>{bundle.mock_server_base_url}</strong>
              </div>
            )}
          </div>
          {bundle.br_setup && (
            <CopyJson label="Business Rule setup" value={bundle.br_setup as Record<string, unknown>} />
          )}

          {bundle.provisioning_log && bundle.provisioning_log.length > 0 && (
            <>
              <div className="data-section-title">Provisioning Log</div>
              <div className="json-panel">
                <pre style={{ fontSize: '0.72rem', lineHeight: '1.6', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
                  {bundle.provisioning_log.map((line, i) => (
                    <span key={i} style={{ display: 'block', borderBottom: '1px solid rgba(128,128,128,0.15)', paddingBottom: '2px', marginBottom: '2px' }}>
                      {line}
                    </span>
                  ))}
                </pre>
              </div>
            </>
          )}
        </>
      )}

      <div className="result-disclosure" style={{ marginTop: '1rem' }}>
        <button
          type="button"
          className="btn ghost result-disclosure-toggle"
          onClick={() => setShowCredentials((current) => !current)}
          aria-expanded={showCredentials}
        >
          <span className={`result-disclosure-arrow ${showCredentials ? 'open' : ''}`}>▾</span>
          {showCredentials ? 'Hide credentials' : 'Show credentials'}
        </button>
      </div>

      {showCredentials && (
        <>
          <div className="data-section-title">Credentials</div>
          <div className="data-grid">
            {bundle.api_key && <CopyRow label="ApiKey" value={bundle.api_key} stacked />}
            {bundle.api_key_id && <CopyRow label="Key ID" value={bundle.api_key_id} stacked />}
          </div>

          {Object.keys(bundle.contracts).length > 0 && (
            <>
              <div className="data-section-title">Contracts</div>
              <div className="data-grid">
                {Object.entries(bundle.contracts).map(([code, id]) => (
                  <CopyRow key={code} label={code} value={id} stacked />
                ))}
              </div>
            </>
          )}

          {Object.keys(bundle.booking_ids).length > 0 && (
            <>
              <div className="data-section-title">Booking IDs</div>
              <div className="data-grid">
                {Object.entries(bundle.booking_ids).map(([code, id]) => (
                  <CopyRow key={code} label={code} value={id} stacked />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {bundle.status === 'READY' && (onRunCrawlaScenario || onRefreshBookingIds || onTeardown) && (
        <div className="actions">
          {onRunCrawlaScenario && (
            <button type="button" className="btn" disabled={actionBusy || runBusy} onClick={onRunCrawlaScenario}>
              {runBusy ? 'Running…' : 'Run scenario'}
            </button>
          )}
          {crawlaRunResult && (crawlaRunResult.logs.length > 0 || crawlaRunResult.error_message) ? (
            <button type="button" className="btn secondary" onClick={onToggleLogs}>
              {showLogs ? 'Hide logs' : 'View logs'}
            </button>
          ) : null}
          {onRefreshBookingIds && (
            <button type="button" className="btn secondary" disabled={actionBusy} onClick={onRefreshBookingIds}>
              ↻ Refresh booking IDs
            </button>
          )}
          {onTeardown && (
            <button type="button" className="btn danger" disabled={actionBusy} onClick={onTeardown}>
              Teardown mocks
            </button>
          )}
        </div>
      )}
    </div>
  )
}
