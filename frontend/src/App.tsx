import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { createCrawlaScenario, runCrawlaScenario } from './api/crawla'
import {
  clearAllScenarios,
  createScenario,
  getHealth,
  listScenarios,
  listSuppliers,
  refreshBookingIds,
  runScenario,
  teardownScenario,
} from './api/client'
import { ScenarioList } from './components/ScenarioList'
import { ScenarioProgress } from './components/ScenarioProgress'
import { ScenarioResult } from './components/ScenarioResult'
import { ScenarioWizard } from './components/ScenarioWizard'
import { useScenarioPoll } from './hooks/useScenarioPoll'
import { CrawlaMocksWizard } from './components/CrawlaMocksWizard'
import { CrawlaQueueRunner } from './components/CrawlaQueueRunner'
import { TestRunDashboard } from './components/TestRunDashboard'
import type { CrawlaScenarioRequest, CrawlaScenarioRunResult } from './types/crawla'
import type { ScenarioListItem, ScenarioRequest, ScenarioStatus } from './types/scenario'

type Tab = 'create' | 'browse' | 'crawla' | 'queue' | 'test-run'

function App() {
  const [tab, setTab] = useState<Tab>('create')
  const [healthOk, setHealthOk] = useState(true)
  const [healthPhase, setHealthPhase] = useState('…')
  const [backendError, setBackendError] = useState<string | null>(null)
  const [supplierCount, setSupplierCount] = useState(0)
  const [scenarioCount, setScenarioCount] = useState(0)

  const [creating, setCreating] = useState(false)
  const [crawlaRunning, setCrawlaRunning] = useState(false)
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null)
  const [crawlaRunResult, setCrawlaRunResult] = useState<CrawlaScenarioRunResult | null>(null)
  const [showCrawlaLogs, setShowCrawlaLogs] = useState(false)
  const { bundle, error: pollError, polling, refresh: refreshBundle } = useScenarioPoll(activeScenarioId)

  const [listItems, setListItems] = useState<ScenarioListItem[]>([])
  const [listLoading, setListLoading] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [clearingAll, setClearingAll] = useState(false)
  const [clearingScenarioIds, setClearingScenarioIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    setCrawlaRunResult(null)
    setShowCrawlaLogs(false)
  }, [activeScenarioId])

  const activeScenarioCount = listItems.filter(
    (item) => item.status !== 'TORN_DOWN' && item.status !== 'PENDING',
  ).length

  const loadList = useCallback(async () => {
    setListLoading(true)
    try {
      const items = await listScenarios()
      setListItems(items)
      setScenarioCount(items.length)
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Failed to load scenarios')
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    Promise.all([getHealth(), listSuppliers()])
      .then(([h, suppliers]) => {
        setHealthPhase(h.phase)
        setHealthOk(h.status === 'ok')
        setSupplierCount(suppliers.length)
        setBackendError(null)
      })
      .catch(() => {
        setHealthOk(false)
        setBackendError('Cannot reach backend — run: python3 -m uvicorn app.main:app --reload --port 8000')
      })
    loadList()
  }, [loadList])

  const handleCreate = async (request: ScenarioRequest) => {
    setCreating(true)
    setBackendError(null)
    try {
      const created = await createScenario(request)
      if (!created.id) throw new Error('Create response missing id')
      setActiveScenarioId(created.id)
      setTab('create')
      await loadList()
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Create failed')
      throw err
    } finally {
      setCreating(false)
    }
  }

  const handleCreateCrawla = async (request: CrawlaScenarioRequest) => {
    setCreating(true)
    setBackendError(null)
    setCrawlaRunResult(null)
    setShowCrawlaLogs(false)
    try {
      const created = await createCrawlaScenario(request)
      if (!created.id) throw new Error('Create response missing id')
      setActiveScenarioId(created.id)
      setTab('crawla')
      await loadList()
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Create failed')
      throw err
    } finally {
      setCreating(false)
    }
  }

  const handleRunCrawlaScenario = async () => {
    if (!activeScenarioId) return
    setCrawlaRunning(true)
    setBackendError(null)
    try {
      // Crawla scenarios carry a crawla_export payload and use the Crawla run route;
      // regular scenarios use the generic scenarios run route (no export required).
      const result = bundle?.crawla_export
        ? await runCrawlaScenario(activeScenarioId)
        : await runScenario(activeScenarioId)
      setCrawlaRunResult(result)
      setShowCrawlaLogs(false)
      await refreshBundle()
      await loadList()
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Scenario run failed')
    } finally {
      setCrawlaRunning(false)
    }
  }

  const handleRefreshBookingIds = async () => {
    if (!activeScenarioId) return
    setActionBusy(true)
    try {
      await refreshBookingIds(activeScenarioId)
      await refreshBundle()
      await loadList()
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Refresh failed')
    } finally {
      setActionBusy(false)
    }
  }

  const handleTeardown = async () => {
    if (!activeScenarioId) return
    setActionBusy(true)
    try {
      const removedId = activeScenarioId
      await teardownScenario(activeScenarioId)
      setActiveScenarioId(null)
      setListItems((items) => items.filter((item) => item.id !== removedId))
      setScenarioCount((count) => Math.max(count - 1, 0))
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Teardown failed')
    } finally {
      setActionBusy(false)
    }
  }

  const handleClearHistoryScenario = async (item: ScenarioListItem) => {
    const confirmed = window.confirm(
      `Clear scenario "${item.namespace}"?\n\nThis removes all data linked with this scenario: MockServer expectations, contracts, apiKey, BR setup, and the history row. Cannot undo.`,
    )
    if (!confirmed) return

    setClearingScenarioIds((ids) => new Set(ids).add(item.id))
    setBackendError(null)
    try {
      await teardownScenario(item.id)
      setListItems((items) => items.filter((existing) => existing.id !== item.id))
      setScenarioCount((count) => Math.max(count - 1, 0))
      if (activeScenarioId === item.id) {
        setActiveScenarioId(null)
        setCrawlaRunResult(null)
        setShowCrawlaLogs(false)
      }
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Clear scenario failed')
    } finally {
      setClearingScenarioIds((ids) => {
        const next = new Set(ids)
        next.delete(item.id)
        return next
      })
    }
  }

  const handleToggleCrawlaLogs = () => {
    setShowCrawlaLogs((current) => !current)
  }

  const handleClearAll = async () => {
    if (activeScenarioCount === 0) return
    const confirmed = window.confirm(
      `Clear all ${activeScenarioCount} active scenario(s)?\n\nThis removes MockServer expectations, backoffice contracts, and apiKeys. Cannot undo.`,
    )
    if (!confirmed) return

    setClearingAll(true)
    setBackendError(null)
    try {
      const result = await clearAllScenarios()
      if (result.queued === 0) return
      const removed = new Set(result.scenario_ids)
      setListItems((items) => items.filter((item) => !removed.has(item.id)))
      setScenarioCount((count) => Math.max(count - result.scenario_ids.length, 0))
      if (activeScenarioId && removed.has(activeScenarioId)) {
        setActiveScenarioId(null)
      }
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Clear all failed')
    } finally {
      setClearingAll(false)
    }
  }

  const showProgress =
    bundle && bundle.status !== 'READY' && bundle.status !== 'FAILED' && bundle.status !== 'TORN_DOWN'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">SMF</div>
          <div className="brand-text">
            <strong>Mock Factory</strong>
            <span>Supplier QA</span>
          </div>
        </div>

        <nav className="side-nav">
          <button
            type="button"
            className={tab === 'create' ? 'nav-item active' : 'nav-item'}
            onClick={() => setTab('create')}
          >
            <span className="nav-icon">✦</span>
            New scenario
          </button>
          <button
            type="button"
            className={tab === 'browse' ? 'nav-item active' : 'nav-item'}
            onClick={() => setTab('browse')}
          >
            <span className="nav-icon">☰</span>
            Scenarios
            {scenarioCount > 0 && ` (${scenarioCount})`}
          </button>
          <button
            type="button"
            className={tab === 'crawla' ? 'nav-item active' : 'nav-item'}
            onClick={() => setTab('crawla')}
          >
            <span className="nav-icon">◌</span>
            Crawla Mocks
          </button>
          <button
            type="button"
            className={tab === 'queue' ? 'nav-item active' : 'nav-item'}
            onClick={() => setTab('queue')}
          >
            <span className="nav-icon">⏵</span>
            Queue Runner
          </button>
          <button
            type="button"
            className={tab === 'test-run' ? 'nav-item active' : 'nav-item'}
            onClick={() => setTab('test-run')}
          >
            <span className="nav-icon">⬡</span>
            Test Runs
          </button>
        </nav>

        <div className="side-stats">
          <div className="stat-chip">
            <span>Backend</span>
            <strong style={{ color: healthOk ? 'var(--success)' : 'var(--danger)' }}>
              {healthOk ? 'Connected' : 'Offline'}
            </strong>
          </div>
          <div className="stat-chip">
            <span>Phase</span>
            <strong>{healthPhase}</strong>
          </div>
          <div className="stat-chip">
            <span>Suppliers</span>
            <strong>{supplierCount} active</strong>
          </div>
        </div>

        <div className="side-actions">
          <button
            type="button"
            className="btn danger full-width"
            onClick={handleClearAll}
            disabled={!healthOk || clearingAll || activeScenarioCount === 0}
            title={
              activeScenarioCount === 0
                ? 'No active scenarios to clear'
                : 'Remove mocks, contracts, and apiKeys for all scenarios'
            }
          >
            {clearingAll ? 'Clearing…' : `Clear all data (${activeScenarioCount})`}
          </button>
        </div>
      </aside>

      <div className="main-panel">
        {backendError && (
          <div className="banner error">
            <span>⚠</span>
            <span>{backendError}</span>
          </div>
        )}

        {tab === 'create' && (
          <>
            <header className="page-header">
              <h1>Create mock scenario</h1>
              <p>Configure HBS + EXP packages, then provision mocks, contracts, and apiKey.</p>
            </header>

            <div className="layout">
              <section className="card">
                <div className="card-header">
                  <div>
                    <h2>Scenario wizard</h2>
                    <p>All fields apply per selected supplier</p>
                  </div>
                </div>
                <ScenarioWizard onSubmit={handleCreate} busy={creating} />

                {activeScenarioId && bundle && (
                  <div className="create-status">
                    <div className="id-badge">
                      ID <code>{activeScenarioId}</code>
                    </div>
                    {showProgress && (
                      <ScenarioProgress status={bundle.status as ScenarioStatus} polling={polling} />
                    )}
                    {pollError && <p className="error-text">{pollError}</p>}
                    <ScenarioResult
                      bundle={bundle}
                      onRunCrawlaScenario={bundle.status === 'READY' ? handleRunCrawlaScenario : undefined}
                      onToggleLogs={
                        crawlaRunResult && (crawlaRunResult.logs.length > 0 || crawlaRunResult.error_message)
                          ? handleToggleCrawlaLogs
                          : undefined
                      }
                      crawlaRunResult={crawlaRunResult}
                      showLogs={showCrawlaLogs}
                      onRefreshBookingIds={bundle.status === 'READY' ? handleRefreshBookingIds : undefined}
                      onTeardown={bundle.status === 'READY' ? handleTeardown : undefined}
                      actionBusy={actionBusy}
                      runBusy={crawlaRunning}
                    />
                  </div>
                )}
              </section>
            </div>
          </>
        )}

        {tab === 'crawla' && (
          <>
            <header className="page-header">
              <h1>Crawla mocks</h1>
              <p>Fetch live Crawla anchors, tune HBS/EXP prices, then provision the scenario export.</p>
            </header>

            <div className="layout">
              <section className="card">
                <div className="card-header">
                  <div>
                    <h2>Crawla wizard</h2>
                    <p>Live anchors, bucket pricing, and export JSON</p>
                  </div>
                </div>
                <CrawlaMocksWizard onSubmit={handleCreateCrawla} busy={creating} />

                {activeScenarioId && bundle && (
                  <div className="create-status">
                    <div className="id-badge">
                      ID <code>{activeScenarioId}</code>
                    </div>
                    {showProgress && (
                      <ScenarioProgress status={bundle.status as ScenarioStatus} polling={polling} />
                    )}
                    {pollError && <p className="error-text">{pollError}</p>}
                    <ScenarioResult
                      bundle={bundle}
                      onRunCrawlaScenario={bundle.status === 'READY' ? handleRunCrawlaScenario : undefined}
                      onToggleLogs={
                        crawlaRunResult && (crawlaRunResult.logs.length > 0 || crawlaRunResult.error_message)
                          ? handleToggleCrawlaLogs
                          : undefined
                      }
                      crawlaRunResult={crawlaRunResult}
                      showLogs={showCrawlaLogs}
                      onRefreshBookingIds={bundle.status === 'READY' ? handleRefreshBookingIds : undefined}
                      onTeardown={bundle.status === 'READY' ? handleTeardown : undefined}
                      actionBusy={actionBusy}
                      runBusy={crawlaRunning}
                    />
                  </div>
                )}
              </section>
            </div>
          </>
        )}

        {tab === 'queue' && (
          <>
            <header className="page-header">
              <h1>Crawla Mock Queue Runner</h1>
              <p>
                Runs all five Crawla bucket scenarios sequentially — each scenario is fully provisioned,
                executed, and cleared before the next one begins.
              </p>
            </header>

            <div className="layout">
              <section className="card">
                <div className="card-header">
                  <div>
                    <h2>Queue runner</h2>
                    <p>Crawla Lower → Expedia Lower → Equal → Only Expedia → Only Crawla</p>
                  </div>
                </div>
                <CrawlaQueueRunner />
              </section>
            </div>
          </>
        )}

        {tab === 'test-run' && (
          <>
            <header className="page-header">
              <h1>Test Runs</h1>
              <p>
                Live dashboard — Smart Booking and Crawla results stream in as Java tests execute.
                Polls every 2s while a run is active.
              </p>
            </header>

            <div className="layout" style={{ height: 'calc(100vh - 130px)', overflow: 'hidden' }}>
              <section className="card" style={{ padding: 0, overflow: 'hidden', height: '100%' }}>
                <TestRunDashboard />
              </section>
            </div>
          </>
        )}

        {tab === 'browse' && (
          <>
            <header className="page-header">
              <h1>Scenario history</h1>
              <p>Browse persisted scenarios from SQLite. Select one to view details.</p>
            </header>

            <div className="layout split">
              <section className="card list-card">
                <ScenarioList
                  items={listItems}
                  selectedId={activeScenarioId}
                  onSelect={(id) => setActiveScenarioId(id)}
                  onClear={handleClearHistoryScenario}
                  onRefresh={loadList}
                  loading={listLoading}
                  clearingIds={clearingScenarioIds}
                />
              </section>

              <section className="card detail-card">
                <div className="card-header">
                  <div>
                    <h2>Scenario detail</h2>
                    {bundle && <p>{bundle.namespace}</p>}
                  </div>
                </div>

                {!activeScenarioId && (
                  <div className="empty-state">
                    <div className="empty-state-icon">◎</div>
                    <p>Select a scenario from the list</p>
                  </div>
                )}

                {activeScenarioId && bundle && (
                  <>
                    <div className="id-badge">
                      ID <code>{activeScenarioId}</code>
                    </div>
                    {showProgress && (
                      <ScenarioProgress status={bundle.status as ScenarioStatus} polling={polling} />
                    )}
                    {pollError && <p className="error-text">{pollError}</p>}
                    <ScenarioResult
                      bundle={bundle}
                      onRunCrawlaScenario={bundle.status === 'READY' ? handleRunCrawlaScenario : undefined}
                      onToggleLogs={
                        crawlaRunResult && (crawlaRunResult.logs.length > 0 || crawlaRunResult.error_message)
                          ? handleToggleCrawlaLogs
                          : undefined
                      }
                      crawlaRunResult={crawlaRunResult}
                      showLogs={showCrawlaLogs}
                      onRefreshBookingIds={bundle.status === 'READY' ? handleRefreshBookingIds : undefined}
                      onTeardown={bundle.status === 'READY' ? handleTeardown : undefined}
                      actionBusy={actionBusy}
                      runBusy={crawlaRunning}
                    />
                  </>
                )}
              </section>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default App
