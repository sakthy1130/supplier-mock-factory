import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { createCrawlaScenario, runCrawlaScenario } from './api/crawla'
import { getActiveEnv, setActiveEnv, type SmfEnv } from './api/base'
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
import { ScenarioWizard, type PackageRow, type ScenarioWizardTemplate } from './components/ScenarioWizard'
import { useScenarioPoll } from './hooks/useScenarioPoll'
import { CrawlaMocksWizard } from './components/CrawlaMocksWizard'
import { CrawlaQueueRunner } from './components/CrawlaQueueRunner'
import { TestRunDashboard, runSuites } from './components/TestRunDashboard'
import { listTestRuns } from './api/testRun'
import {
  createScenarioTemplate,
  deleteScenarioTemplate,
  listScenarioTemplates,
  updateScenarioTemplate,
  type ApiScenarioTemplate,
} from './api/scenarioTemplates'
import { formatStatus, statusClass, timeAgo } from './utils/scenarioFormat'
import { parseTemplatePackagesJson } from './utils/templateImport'
import type { CrawlaScenarioRequest, CrawlaScenarioRunResult } from './types/crawla'
import type { ScenarioListItem, ScenarioRequest, ScenarioStatus, SupplierCode } from './types/scenario'
import type { TestRunState } from './types/testRun'

type Tab = 'home' | 'create' | 'browse' | 'crawla' | 'queue' | 'test-run' | 'templates'

const NAV_ITEMS: { tab: Tab; icon: string; label: string }[] = [
  { tab: 'create', icon: '✦', label: 'Create Mock Scenario' },
  { tab: 'browse', icon: '☰', label: 'Scenario History' },
  { tab: 'crawla', icon: '◌', label: 'Crawla Mocks' },
  { tab: 'queue', icon: '⏵', label: 'Queue Runner' },
  { tab: 'test-run', icon: '⬡', label: 'Test Runs' },
  { tab: 'templates', icon: '🛏', label: 'Template Bedding Mock' },
]

interface ImportSupplierBlock {
  supplier: SupplierCode
  supplier_currency: string
  contract_currency: string
  json: string
}

function nextUnusedSupplier(used: SupplierCode[]): SupplierCode {
  const all: SupplierCode[] = ['HBS', 'EXP', 'RHK', 'CHC', 'EXT']
  return all.find((code) => !used.includes(code)) ?? 'HBS'
}

interface ScenarioTemplate {
  id: string
  label: string
  description: string
  template?: ScenarioWizardTemplate
}

function App() {
  const [tab, setTab] = useState<Tab>('home')
  const [activeTemplate, setActiveTemplate] = useState<ScenarioTemplate | undefined>(undefined)
  const [customTemplates, setCustomTemplates] = useState<ApiScenarioTemplate[]>([])
  const [templatesLoading, setTemplatesLoading] = useState(false)
  const [showImportForm, setShowImportForm] = useState(false)
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null)
  const [importLabel, setImportLabel] = useState('')
  const [importDescription, setImportDescription] = useState('')
  const [importHotelId, setImportHotelId] = useState('')
  const [importSuppliers, setImportSuppliers] = useState<ImportSupplierBlock[]>([
    { supplier: 'HBS', supplier_currency: 'EUR', contract_currency: 'USD', json: '' },
  ])
  const [importError, setImportError] = useState<string | null>(null)
  const [importBusy, setImportBusy] = useState(false)
  const [env, setEnv] = useState<SmfEnv>(getActiveEnv())
  const [healthOk, setHealthOk] = useState(true)
  const [healthDetails, setHealthDetails] = useState<{ status: string; message?: string; checks?: Record<string, { status: string; message: string }> } | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [supplierCount, setSupplierCount] = useState(0)
  const [supplierCodes, setSupplierCodes] = useState<string[]>([])
  const [scenarioCount, setScenarioCount] = useState(0)
  const [lastRun, setLastRun] = useState<TestRunState | null>(null)

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
  const tornDownCount = listItems.filter((item) => item.status === 'TORN_DOWN').length
  const recentScenarios = [...listItems]
    .sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? ''))
    .slice(0, 3)

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
        setHealthDetails(h)
        setHealthOk(h.status === 'ok' || h.status === 'degraded')
        setSupplierCount(suppliers.length)
        setSupplierCodes(suppliers.map((s) => s.code))
        setBackendError(null)
      })
      .catch(() => {
        setHealthOk(false)
        setHealthDetails(null)
        setBackendError('Cannot reach backend — run: python3 -m uvicorn app.main:app --reload --port 8000')
      })
    loadList()
  }, [loadList])

  useEffect(() => {
    if (tab !== 'home') return
    listTestRuns()
      .then((runs) => {
        const sorted = [...runs].sort((a, b) => b.started_at.localeCompare(a.started_at))
        setLastRun(sorted[0] ?? null)
      })
      .catch(() => {
        // Home's "last test run" stat is best-effort — leave it blank on failure
        // rather than surfacing a banner error for a secondary dashboard stat.
      })
  }, [tab])

  const handleEnvChange = async (next: SmfEnv) => {
    if (next === env) return
    setActiveEnv(next)
    setEnv(next)
    // Scenario lists/actions are env-scoped — the previously active scenario may
    // not belong to the newly selected env, so clear the detail view and reload.
    setActiveScenarioId(null)
    setCrawlaRunResult(null)
    setShowCrawlaLogs(false)
    setBackendError(null)
    try {
      const [h, suppliers] = await Promise.all([getHealth(), listSuppliers()])
      setHealthDetails(h)
      setHealthOk(h.status === 'ok' || h.status === 'degraded')
      setSupplierCount(suppliers.length)
      setSupplierCodes(suppliers.map((s) => s.code))
    } catch {
      setHealthOk(false)
      setHealthDetails(null)
      setBackendError('Cannot reach backend — run: python3 -m uvicorn app.main:app --reload --port 8000')
    }
    await loadList()
  }

  // ScenarioWizard only reads its seed template on mount, and it fully
  // unmounts whenever tab !== 'create' (see the conditional render below) —
  // so setting activeTemplate right before switching tabs is enough to seed
  // a fresh instance, and clearing it on every *other* path to 'create'
  // prevents a stale template silently reapplying to a normal new scenario.
  // The wizard is also keyed on the template's id so picking a *different*
  // template while already on the Create tab forces a fresh remount too.
  const openCreate = (template?: ScenarioTemplate) => {
    setActiveTemplate(template)
    setTab('create')
  }

  const loadCustomTemplates = useCallback(async () => {
    setTemplatesLoading(true)
    try {
      setCustomTemplates(await listScenarioTemplates())
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Failed to load templates')
    } finally {
      setTemplatesLoading(false)
    }
  }, [])

  useEffect(() => {
    if (tab === 'templates') loadCustomTemplates()
  }, [tab, loadCustomTemplates])

  const addImportSupplierBlock = () => {
    const nextSupplier = nextUnusedSupplier(importSuppliers.map((b) => b.supplier))
    setImportSuppliers((prev) => [...prev, { supplier: nextSupplier, supplier_currency: 'EUR', contract_currency: 'USD', json: '' }])
  }

  const removeImportSupplierBlock = (index: number) => {
    setImportSuppliers((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)))
  }

  const updateImportSupplierBlock = (index: number, patch: Partial<ImportSupplierBlock>) => {
    setImportSuppliers((prev) => prev.map((block, i) => (i === index ? { ...block, ...patch } : block)))
  }

  const resetImportForm = () => {
    setImportLabel('')
    setImportDescription('')
    setImportHotelId('')
    setImportSuppliers([{ supplier: 'HBS', supplier_currency: 'EUR', contract_currency: 'USD', json: '' }])
    setEditingTemplateId(null)
    setImportError(null)
    setShowImportForm(false)
  }

  const handleImportTemplate = async (e: React.FormEvent) => {
    e.preventDefault()
    setImportError(null)
    setImportBusy(true)
    try {
      const codes = importSuppliers.map((b) => b.supplier)
      const duplicate = codes.find((code, i) => codes.indexOf(code) !== i)
      if (duplicate) {
        throw new Error(`${duplicate} is added more than once — each supplier can only appear once per template`)
      }
      const suppliers = importSuppliers.map((block) => ({
        supplier: block.supplier,
        supplier_currency: block.supplier_currency.toUpperCase().slice(0, 3),
        contract_currency: block.contract_currency.toUpperCase().slice(0, 3),
        packages: parseTemplatePackagesJson(block.json),
      }))
      const payload = {
        label: importLabel.trim(),
        description: importDescription.trim(),
        atg_hotel_id: importHotelId.trim(),
        suppliers,
      }
      if (editingTemplateId) {
        await updateScenarioTemplate(editingTemplateId, payload)
      } else {
        await createScenarioTemplate(payload)
      }
      resetImportForm()
      await loadCustomTemplates()
    } catch (err) {
      setImportError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImportBusy(false)
    }
  }

  const handleEditTemplate = (item: ApiScenarioTemplate) => {
    setEditingTemplateId(item.id)
    setImportLabel(item.label)
    setImportDescription(item.description)
    setImportHotelId(item.atg_hotel_id)
    setImportSuppliers(
      item.suppliers.map((entry) => ({
        supplier: entry.supplier as SupplierCode,
        supplier_currency: entry.supplier_currency,
        contract_currency: entry.contract_currency,
        json: JSON.stringify(entry.packages, null, 2),
      })),
    )
    setImportError(null)
    setShowImportForm(true)
  }

  const handleDeleteTemplate = async (item: ApiScenarioTemplate) => {
    const confirmed = window.confirm(`Delete template "${item.label}"? This cannot be undone.`)
    if (!confirmed) return
    try {
      await deleteScenarioTemplate(item.id)
      if (editingTemplateId === item.id) resetImportForm()
      await loadCustomTemplates()
    } catch (err) {
      setBackendError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  const openCustomTemplate = (item: ApiScenarioTemplate) => {
    const packages: Partial<Record<SupplierCode, PackageRow[]>> = {}
    const enabledSuppliers: Partial<Record<SupplierCode, boolean>> = { HBS: false, EXP: false, RHK: false, CHC: false, EXT: false }
    const supplierCurrencies: Partial<Record<SupplierCode, string>> = {}
    const contractCurrencies: Partial<Record<SupplierCode, string>> = {}
    for (const entry of item.suppliers) {
      const code = entry.supplier as SupplierCode
      packages[code] = entry.packages.map((p) => ({
        roomName: p.room_name,
        roomBasis: p.room_basis,
        price: String(p.price),
        refundable: p.refundable,
      }))
      enabledSuppliers[code] = true
      supplierCurrencies[code] = entry.supplier_currency
      contractCurrencies[code] = entry.contract_currency
    }
    openCreate({
      id: `custom-${item.id}`,
      label: item.label,
      description: item.description,
      template: {
        atgHotelId: item.atg_hotel_id || undefined,
        enabledSuppliers,
        packages,
        supplierCurrencies,
        contractCurrencies,
      },
    })
  }

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
        <button
          type="button"
          className="brand"
          onClick={() => setTab('home')}
          style={{ border: 'none', background: 'none', cursor: 'pointer' }}
        >
          <div className="brand-mark">SMF</div>
        </button>

        <nav className="side-nav">
          <button
            type="button"
            className={`nav-item ${tab === 'home' ? 'active' : ''}`}
            onClick={() => setTab('home')}
          >
            <span className="nav-icon">⌂</span>
            <span className="nav-tip">Home</span>
          </button>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.tab}
              type="button"
              className={`nav-item ${tab === item.tab ? 'active' : ''}`}
              onClick={() => (item.tab === 'create' ? openCreate(undefined) : setTab(item.tab))}
            >
              <span className="nav-icon">{item.icon}</span>
              <span className="nav-tip">
                {item.label}
                {item.tab === 'browse' && scenarioCount > 0 && ` (${scenarioCount})`}
              </span>
            </button>
          ))}
        </nav>

        <div className="side-actions">
          <button
            type="button"
            className="icon-action danger"
            onClick={handleClearAll}
            disabled={!healthOk || clearingAll || activeScenarioCount === 0}
          >
            <span className="nav-icon">🗑</span>
            <span className="nav-tip">
              {activeScenarioCount === 0
                ? 'No active scenarios to clear'
                : clearingAll
                  ? 'Clearing…'
                  : `Clear all data (${activeScenarioCount})`}
            </span>
          </button>
        </div>
      </aside>

      <div className={`main-panel ${tab === 'home' ? 'main-panel--wide' : ''}`}>
          {backendError && (
            <div className="banner error">
              <span>⚠</span>
              <span>{backendError}</span>
            </div>
          )}

        {tab === 'home' && (
          <>
            <section className="hero">
              <span className="page-eyebrow">Enigma Core</span>
              <h1>Supplier Mock Factory</h1>
              <p className="hero-sub">
                Provision supplier mocks, contracts, and apiKeys for HBS, EXP, RHK, and CHC — then run
                tests and queue scenarios from one place.
              </p>
            </section>

            <section className="actions-section">
              <div className="actions-heading">
                <h2>What do you want to do?</h2>
                <p>Pick a workflow to provision mocks, run tests, or inspect existing scenarios.</p>
              </div>

              <div className="home-menu">
                <button type="button" className="home-tile tile-create" onClick={() => openCreate(undefined)}>
                  <span className="home-tile-icon">✦</span>
                  <div className="home-tile-body">
                    <strong>Create Mock Scenario</strong>
                    <span>Configure packages and provision mocks, contracts, and apiKey</span>
                  </div>
                </button>
                <button type="button" className="home-tile tile-browse" onClick={() => setTab('browse')}>
                  <span className="home-tile-icon">☰</span>
                  <div className="home-tile-body">
                    <strong>Scenario History</strong>
                    <span>Browse persisted scenarios and inspect details</span>
                  </div>
                </button>
                <button type="button" className="home-tile tile-crawla" onClick={() => setTab('crawla')}>
                  <span className="home-tile-icon">◌</span>
                  <div className="home-tile-body">
                    <strong>Crawla Mocks</strong>
                    <span>Fetch live Crawla anchors and provision a scenario export</span>
                  </div>
                </button>
                <button type="button" className="home-tile tile-queue" onClick={() => setTab('queue')}>
                  <span className="home-tile-icon">⏵</span>
                  <div className="home-tile-body">
                    <strong>Crawla Mock Queue Runner</strong>
                    <span>Run all Crawla bucket scenarios sequentially</span>
                  </div>
                </button>
                <button type="button" className="home-tile tile-test" onClick={() => setTab('test-run')}>
                  <span className="home-tile-icon">⬡</span>
                  <div className="home-tile-body">
                    <strong>Test Runs</strong>
                    <span>Live dashboard for Smart Booking and Crawla test results</span>
                  </div>
                </button>
                <button type="button" className="home-tile tile-templates" onClick={() => setTab('templates')}>
                  <span className="home-tile-icon">🛏</span>
                  <div className="home-tile-body">
                    <strong>Template Bedding Mock</strong>
                    <span>Provision known bedding-name test scenarios from a preset</span>
                  </div>
                </button>
              </div>
            </section>

            <div className="stats-strip">
              <div className="mini-stat">
                <div className="label">Suppliers</div>
                <div className="value">{supplierCount}</div>
                <div className="hint">{supplierCodes.join(' · ') || '—'}</div>
              </div>
              <div className="mini-stat">
                <div className="label">Scenarios</div>
                <div className="value">{scenarioCount}</div>
                <div className="hint">
                  {activeScenarioCount} active · {tornDownCount} torn down
                </div>
              </div>
              <div className="mini-stat">
                <div className="label">Last test run</div>
                {lastRun ? (
                  <>
                    <div className="value" style={{ fontSize: '1rem' }}>
                      {timeAgo(lastRun.completed_at ?? lastRun.started_at)}
                    </div>
                    <div className="hint">
                      {runSuites(lastRun.results).join(' + ') || 'Tests'} ·{' '}
                      {lastRun.status === 'RUNNING'
                        ? 'running'
                        : lastRun.failed > 0
                          ? `${lastRun.failed} failed`
                          : 'passed'}
                    </div>
                  </>
                ) : (
                  <>
                    <div className="value" style={{ fontSize: '1rem', color: 'var(--text-muted)' }}>
                      —
                    </div>
                    <div className="hint">No runs yet</div>
                  </>
                )}
              </div>
            </div>

            <section className="recent-panel">
              <div className="recent-header">
                <h2>Recent scenarios</h2>
                <button type="button" className="link-btn" onClick={() => setTab('browse')}>
                  View all →
                </button>
              </div>

              {recentScenarios.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon">∅</div>
                  <p>No scenarios yet</p>
                </div>
              ) : (
                <div className="scenario-rows">
                  {recentScenarios.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      className="scenario-row"
                      onClick={() => {
                        setActiveScenarioId(item.id)
                        setTab('browse')
                      }}
                    >
                      <div>
                        <div className="ns">{item.namespace}</div>
                        <div className="meta">
                          {item.suppliers.join(' · ')}
                          {item.created_at && ` · ${timeAgo(item.created_at)}`}
                        </div>
                      </div>
                      <span className={`env-badge env-${item.env}`}>{item.env}</span>
                      <span className={statusClass(item.status)}>{formatStatus(item.status)}</span>
                    </button>
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        {tab === 'create' && (
          <>
            <header className="page-header">
              <span className="page-eyebrow">Provisioning</span>
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
                {activeTemplate && (
                  <div className="banner" style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}>
                    <span>❖</span>
                    <span>
                      Prefilled from <strong>{activeTemplate.label}</strong> —{' '}
                      <button type="button" className="link-btn" onClick={() => openCreate(undefined)}>
                        start blank instead
                      </button>
                    </span>
                  </div>
                )}
                <ScenarioWizard
                  key={activeTemplate?.id ?? 'blank'}
                  onSubmit={handleCreate}
                  busy={creating}
                  initialTemplate={activeTemplate?.template}
                />

                {activeScenarioId && bundle && (
                  <div className="create-status">
                    <div className="id-badge">
                      ID <code>{activeScenarioId}</code>
                      <span className={`env-badge env-${bundle.env}`} style={{ marginLeft: '0.5rem' }}>
                        {bundle.env}
                      </span>
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
              <span className="page-eyebrow">Live Anchors</span>
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
                      <span className={`env-badge env-${bundle.env}`} style={{ marginLeft: '0.5rem' }}>
                        {bundle.env}
                      </span>
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
              <span className="page-eyebrow">Automation</span>
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
              <span className="page-eyebrow">Live Dashboard</span>
              <h1>Test Runs</h1>
              <p>
                Live dashboard — Smart Booking and Crawla results stream in as Java tests execute.
                Polls every 2s while a run is active.
              </p>
            </header>

            <div className="layout" style={{ height: 'calc(100vh - 210px)', overflow: 'hidden' }}>
              <section className="card" style={{ padding: 0, overflow: 'hidden', height: '100%' }}>
                <TestRunDashboard />
              </section>
            </div>
          </>
        )}

        {tab === 'templates' && (
          <>
            <header className="page-header">
              <span className="page-eyebrow">Presets</span>
              <h1>Template Bedding Mock</h1>
              <p>
                Pick a preset to open Create Mock Scenario prefilled with known package data — edit anything
                before provisioning, same as a normal scenario.
              </p>
            </header>

            <div className="banner error" style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}>
              <span>⚠</span>
              <span>
                Templates commonly share the same ATG hotel ID (e.g. <code>1010102</code>). HBS resolves
                packages per hotel ID across <em>all</em> active contracts, not per-scenario — if two
                scenarios using the same hotel ID are both READY at once, HBS will merge packages from
                both. Tear down the previous scenario for that hotel before creating a new one from a
                template.
              </span>
            </div>

            <section className="recent-panel" style={{ marginTop: '1.5rem' }}>
              <div className="recent-header">
                <h2>Custom templates</h2>
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => (showImportForm ? resetImportForm() : setShowImportForm(true))}
                >
                  {showImportForm ? 'Cancel' : '+ Import template'}
                </button>
              </div>

              {showImportForm && (
                <form className="wizard-section" onSubmit={handleImportTemplate} style={{ marginBottom: '1rem' }}>
                  <div className="wizard-section-title">
                    {editingTemplateId ? 'Edit template' : 'New template'}
                  </div>
                  <div className="field-grid">
                    <div className="field">
                      <label>
                        Label
                        <input
                          value={importLabel}
                          onChange={(e) => setImportLabel(e.target.value)}
                          required
                          maxLength={120}
                          placeholder="Scenario4"
                        />
                      </label>
                    </div>
                    <div className="field">
                      <label>
                        ATG hotel ID
                        <input
                          value={importHotelId}
                          onChange={(e) => setImportHotelId(e.target.value)}
                          required
                          placeholder="1010102"
                        />
                      </label>
                    </div>
                    <div className="field field-wide">
                      <label>
                        Description (optional)
                        <input
                          value={importDescription}
                          onChange={(e) => setImportDescription(e.target.value)}
                          placeholder="What this preset is for"
                        />
                      </label>
                    </div>
                  </div>

                  <div className="wizard-section-title" style={{ marginTop: '1rem' }}>
                    Suppliers
                  </div>
                  {importSuppliers.map((block, index) => (
                    <div key={index} className="wizard-section" style={{ marginBottom: '0.75rem' }}>
                      <div className="field-row" style={{ alignItems: 'flex-end', marginBottom: '0.5rem' }}>
                        <div className="field" style={{ maxWidth: '160px' }}>
                          <label>
                            Supplier
                            <select
                              value={block.supplier}
                              onChange={(e) =>
                                updateImportSupplierBlock(index, { supplier: e.target.value as SupplierCode })
                              }
                            >
                              <option value="HBS">HBS</option>
                              <option value="EXP">EXP</option>
                              <option value="RHK">RHK</option>
                              <option value="CHC">CHC</option>
                              <option value="EXT">EXT</option>
                            </select>
                          </label>
                        </div>
                        <button
                          type="button"
                          className="btn ghost"
                          onClick={() => removeImportSupplierBlock(index)}
                          disabled={importSuppliers.length <= 1}
                          title="Remove this supplier"
                        >
                          × Remove
                        </button>
                      </div>
                      <div className="field-grid" style={{ marginBottom: '0.5rem' }}>
                        <div className="field" style={{ maxWidth: '140px' }}>
                          <label>
                            Supplier Currency
                            <input
                              value={block.supplier_currency}
                              onChange={(e) =>
                                updateImportSupplierBlock(index, { supplier_currency: e.target.value })
                              }
                              maxLength={3}
                              placeholder="EUR"
                              required
                            />
                          </label>
                        </div>
                        <div className="field" style={{ maxWidth: '140px' }}>
                          <label>
                            Contract Currency
                            <select
                              value={block.contract_currency}
                              onChange={(e) =>
                                updateImportSupplierBlock(index, { contract_currency: e.target.value })
                              }
                              required
                            >
                              <option value="">— Select —</option>
                              <option value="SAR">SAR</option>
                              <option value="AED">AED</option>
                              <option value="USD">USD</option>
                              <option value="EUR">EUR</option>
                            </select>
                          </label>
                        </div>
                      </div>
                      <div className="field field-wide">
                        <label>
                          Packages JSON
                          <textarea
                            value={block.json}
                            onChange={(e) => updateImportSupplierBlock(index, { json: e.target.value })}
                            required
                            rows={6}
                            placeholder={
                              '[\n  { "roomName": "...", "price": 300, "roomBasis": "RO", "refundable": true }\n]'
                            }
                          />
                        </label>
                      </div>
                    </div>
                  ))}
                  <button type="button" className="btn ghost" onClick={addImportSupplierBlock}>
                    + Add supplier
                  </button>

                  {importError && <p className="error-text">{importError}</p>}
                  <div className="form-footer">
                    <p className="hint">Accepts roomName/room_name, price, roomBasis/room_basis, refundable — any casing.</p>
                    <button type="submit" className="btn primary" disabled={importBusy}>
                      {importBusy ? 'Saving…' : editingTemplateId ? 'Save changes' : 'Save template'}
                    </button>
                  </div>
                </form>
              )}

              {templatesLoading ? (
                <p className="hint">Loading…</p>
              ) : customTemplates.length === 0 ? (
                <div className="empty-state">
                  <div className="empty-state-icon">∅</div>
                  <p>No custom templates yet</p>
                </div>
              ) : (
                <div className="scenario-rows">
                  {customTemplates.map((item) => (
                    <div key={item.id} className="scenario-row">
                      <button type="button" className="list-item" onClick={() => openCustomTemplate(item)}>
                        <div className="ns">{item.label}</div>
                        <div className="meta">
                          {item.suppliers
                            .map((s) => `${s.supplier} (${s.packages.length})`)
                            .join(' · ')}
                          {item.description && ` · ${item.description}`}
                        </div>
                      </button>
                      <span style={{ display: 'flex', gap: '0.3rem' }}>
                        {item.suppliers.map((s) => (
                          <span
                            key={s.supplier}
                            className="env-badge"
                            style={{
                              color: `var(--${s.supplier.toLowerCase()})`,
                              borderColor: `color-mix(in srgb, var(--${s.supplier.toLowerCase()}) 55%, transparent)`,
                              background: `color-mix(in srgb, var(--${s.supplier.toLowerCase()}) 10%, transparent)`,
                            }}
                          >
                            {s.supplier}
                          </span>
                        ))}
                      </span>
                      <span style={{ display: 'flex', gap: '0.4rem' }}>
                        <button type="button" className="btn ghost tiny" onClick={() => handleEditTemplate(item)}>
                          Edit
                        </button>
                        <button type="button" className="btn danger tiny" onClick={() => handleDeleteTemplate(item)}>
                          Delete
                        </button>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        {tab === 'browse' && (
          <>
            <header className="page-header">
              <span className="page-eyebrow">History</span>
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
                      <span className={`env-badge env-${bundle.env}`} style={{ marginLeft: '0.5rem' }}>
                        {bundle.env}
                      </span>
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

      {/* Right sidebar with environment and backend status */}
      <aside className="right-sidebar">
        <div className="sidebar-section">
          <label className="sidebar-label">🌐 Environment</label>
          <select
            className={`sidebar-select ${env === 'stg' ? 'env-stg' : 'env-dev'}`}
            value={env}
            onChange={(e) => handleEnvChange(e.target.value as SmfEnv)}
          >
            <option value="dev">Dev</option>
            <option value="stg">Staging</option>
          </select>
        </div>

        <div className="sidebar-section">
          <label className="sidebar-label">🔗 Backend Status</label>
          <div className="sidebar-status" style={{ color: healthOk ? 'var(--success)' : 'var(--danger)' }}>
            <span
              className="pulse-dot"
              style={{
                background: healthOk ? 'var(--success)' : 'var(--danger)',
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                display: 'inline-block',
              }}
            />
            {healthOk ? 'Connected' : 'Offline'}
          </div>
          {healthDetails && (
            <div className="health-checks">
              {healthDetails.checks && (
                <div style={{ marginTop: '0.6rem', fontSize: '0.75rem' }}>
                  {Object.entries(healthDetails.checks).map(([key, check]) => (
                    <div
                      key={key}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        padding: '0.3rem 0',
                        color: check.status === 'ok' ? 'var(--success)' : 'var(--danger)',
                      }}
                    >
                      <span style={{ fontSize: '0.6rem' }}>
                        {check.status === 'ok' ? '✓' : '✗'}
                      </span>
                      <span style={{ textTransform: 'capitalize' }}>
                        {key.replace('_', ' ')}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {healthDetails.message && (
                <div style={{ marginTop: '0.6rem', fontSize: '0.7rem', color: 'var(--text-muted)', lineHeight: '1.3' }}>
                  {healthDetails.message}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  )
}

export default App
