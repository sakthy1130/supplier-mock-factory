import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ALL_LOG_TYPES,
  createSupplier,
  deleteSupplier,
  emptySupplierConfig,
  generateSupplierFieldMap,
  getSupplierReadiness,
  ingestSupplierFromSid,
  listSupplierConfigs,
  probeSupplier,
  toPayload,
  updateSupplier,
  uploadSupplierTemplate,
  type ApiIngestResult,
  type ApiProbeResult,
  type ApiSupplierConfig,
  type ApiSupplierReadiness,
  type SupplierConfigPayload,
} from '../api/suppliers'

const NEW_CODE = '__new__'

/** Comma-separated text <-> string[] for the key-list fields. */
function splitKeys(value: string): string[] {
  return value
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
}

function readinessLabel(readiness: ApiSupplierReadiness | undefined): {
  cls: string
  text: string
} {
  if (!readiness) return { cls: '', text: 'Checking…' }
  if (readiness.ready) return { cls: 'ok', text: 'Ready to mock' }
  const blocking = readiness.checks.filter((c) => c.blocking && !c.ok).length
  return { cls: blocking ? 'bad' : 'warn', text: `${blocking} thing${blocking === 1 ? '' : 's'} missing` }
}

interface Props {
  env: string
  /** Lets the dashboard counters refresh after a supplier is added or removed. */
  onSuppliersChanged?: () => void
}

export function SupplierRegistry({ env, onSuppliersChanged }: Props) {
  const [configs, setConfigs] = useState<ApiSupplierConfig[]>([])
  const [readiness, setReadiness] = useState<Record<string, ApiSupplierReadiness>>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Which tile is expanded: a supplier code, NEW_CODE, or null for none.
  const [openCode, setOpenCode] = useState<string | null>(null)
  const [draft, setDraft] = useState<SupplierConfigPayload | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [probe, setProbe] = useState<ApiProbeResult | null>(null)
  const [sid, setSid] = useState('')
  const [ingest, setIngest] = useState<ApiIngestResult | null>(null)
  // Ingest errors get their own slot: formError renders at the very bottom of the
  // card, far below the Build-templates button, so a failure there looks like nothing happened.
  const [ingestError, setIngestError] = useState<string | null>(null)

  const editorRef = useRef<HTMLDivElement | null>(null)

  const load = useCallback(async () => {
    try {
      const items = await listSupplierConfigs()
      const entries = await Promise.all(
        items.map(async (item) => [item.code, await getSupplierReadiness(item.code)] as const),
      )
      setConfigs(items)
      setReadiness(Object.fromEntries(entries))
      setLoadError(null)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load suppliers')
    } finally {
      setLoading(false)
    }
  }, [])

  // App remounts this on an env change (key={env}), so there's nothing to reset
  // here — a supplier open in one env may not even exist in the other.
  useEffect(() => {
    void load()
  }, [load])

  const isNew = openCode === NEW_CODE

  const openEditor = useCallback(
    (code: string) => {
      setFormError(null)
      setNotice(null)
      setProbe(null)
      setIngest(null)
      setIngestError(null)
      setSid('')
      if (code === NEW_CODE) {
        setDraft(emptySupplierConfig())
      } else {
        const config = configs.find((c) => c.code === code)
        if (!config) return
        setDraft(toPayload(config))
      }
      setOpenCode(code)
      // The editor sits below the grid, so it can open off-screen.
      requestAnimationFrame(() => {
        editorRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    },
    [configs],
  )

  const closeEditor = useCallback(() => {
    setOpenCode(null)
    setDraft(null)
    setProbe(null)
    setIngest(null)
    setIngestError(null)
    setFormError(null)
    setNotice(null)
  }, [])

  const patch = useCallback((changes: Partial<SupplierConfigPayload>) => {
    setDraft((current) => (current ? { ...current, ...changes } : current))
  }, [])

  const patchMock = useCallback(
    (changes: Partial<SupplierConfigPayload['mock_config']>) => {
      setDraft((current) =>
        current ? { ...current, mock_config: { ...current.mock_config, ...changes } } : current,
      )
    },
    [],
  )

  const patchMutation = useCallback(
    (changes: Partial<SupplierConfigPayload['mutation_config']>) => {
      setDraft((current) =>
        current
          ? { ...current, mutation_config: { ...current.mutation_config, ...changes } }
          : current,
      )
    },
    [],
  )

  const handleSave = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault()
      if (!draft) return
      const code = draft.code.trim().toUpperCase()

      if (!/^[A-Z0-9]{2,8}$/.test(code)) {
        setFormError('Supplier code must be 2–8 letters or digits, e.g. AGD')
        return
      }
      if (isNew && configs.some((c) => c.code === code)) {
        setFormError(`${code} already exists in ${env}`)
        return
      }
      if (!draft.log_types.includes('Packages')) {
        setFormError('Packages is required — it is the response a scenario builds from')
        return
      }
      if (!draft.name.trim()) {
        setFormError('Give the supplier a display name')
        return
      }

      setBusy(true)
      setFormError(null)
      try {
        const payload = { ...draft, code }
        const saved = isNew ? await createSupplier(payload) : await updateSupplier(code, payload)
        await load()
        onSuppliersChanged?.()
        setDraft(toPayload(saved))
        setOpenCode(saved.code)
        setNotice(isNew ? `${saved.code} added` : `${saved.code} saved`)
      } catch (err) {
        setFormError(err instanceof Error ? err.message : 'Failed to save supplier')
      } finally {
        setBusy(false)
      }
    },
    [configs, draft, env, isNew, load, onSuppliersChanged],
  )

  const handleDelete = useCallback(async () => {
    if (!draft || isNew) return
    if (!window.confirm(`Delete ${draft.code} from ${env}? Its templates stay on disk.`)) return
    setBusy(true)
    try {
      await deleteSupplier(draft.code)
      closeEditor()
      await load()
      onSuppliersChanged?.()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to delete supplier')
    } finally {
      setBusy(false)
    }
  }, [closeEditor, draft, env, isNew, load, onSuppliersChanged])

  const handleProbe = useCallback(async () => {
    if (!draft || isNew) return
    setBusy(true)
    setProbe(null)
    try {
      setProbe(await probeSupplier(draft.code))
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Test run failed')
    } finally {
      setBusy(false)
    }
  }, [draft, isNew])

  const handleIngest = useCallback(async () => {
    if (!draft || isNew) return
    const trimmed = sid.trim()
    if (!trimmed) {
      setIngestError('Enter the SID whose adapter logs the templates should come from')
      return
    }
    const source = draft.mutation_config.adapter_source_match.trim()
    if (!source) {
      setIngestError(
        `Enter the adapter log source first — without it no log row in the SID can be ` +
          `attributed to ${draft.code} (e.g. hotels-derby-bts-adapter)`,
      )
      return
    }
    setBusy(true)
    setFormError(null)
    setNotice(null)
    setIngest(null)
    setIngestError(null)
    try {
      // The ingest attributes log rows using the SAVED registry config, not this draft,
      // so a source match typed here has to be persisted before it can match anything.
      const saved = configs.find((c) => c.code === draft.code)
      if (saved?.mutation_config.adapter_source_match !== source) {
        const updated = await updateSupplier(draft.code, {
          ...draft,
          mutation_config: { ...draft.mutation_config, adapter_source_match: source },
        })
        setDraft(toPayload(updated))
      }
      const result = await ingestSupplierFromSid(draft.code, trimmed)
      setIngest(result)
      if (result.written.length) {
        setNotice(
          `Built ${result.written.length} template${result.written.length === 1 ? '' : 's'} from SID ${trimmed}`,
        )
      }
      // Templates on disk changed, so the readiness checklist has too.
      await load()
    } catch (err) {
      setIngestError(err instanceof Error ? err.message : 'Ingest failed')
    } finally {
      setBusy(false)
    }
  }, [configs, draft, isNew, load, sid])

  const handleGenerateFieldMap = useCallback(async () => {
    if (!draft || isNew) return
    setBusy(true)
    try {
      const fieldMap = await generateSupplierFieldMap(draft.code)
      patch({ field_map: fieldMap })
      const paths = (fieldMap.paths ?? {}) as Record<string, string[]>
      const found = Object.values(paths).reduce((sum, list) => sum + list.length, 0)
      setNotice(`Field map generated — ${found} path${found === 1 ? '' : 's'} found`)
      await load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to generate field map')
    } finally {
      setBusy(false)
    }
  }, [draft, isNew, load, patch])

  const handleTemplateUpload = useCallback(
    async (logType: string, file: File) => {
      if (!draft || isNew) return
      setBusy(true)
      setFormError(null)
      try {
        const text = await file.text()
        const expectation = JSON.parse(text) as unknown
        const result = await uploadSupplierTemplate(draft.code, logType, expectation)
        setNotice(`${logType} saved to ${result.path}`)
        await load()
      } catch (err) {
        setFormError(
          err instanceof SyntaxError
            ? `${file.name} is not valid JSON`
            : err instanceof Error
              ? err.message
              : 'Failed to upload template',
        )
      } finally {
        setBusy(false)
      }
    },
    [draft, isNew, load],
  )

  const toggleLogType = useCallback(
    (logType: string) => {
      setDraft((current) => {
        if (!current) return current
        const has = current.log_types.includes(logType)
        const log_types = has
          ? current.log_types.filter((lt) => lt !== logType)
          : [...ALL_LOG_TYPES].filter((lt) => lt === logType || current.log_types.includes(lt))
        return {
          ...current,
          log_types,
          // A log type that is no longer served can't be mutated either.
          package_log_types: current.package_log_types.filter((lt) => log_types.includes(lt)),
        }
      })
    },
    [],
  )

  const togglePackageLogType = useCallback((logType: string) => {
    setDraft((current) => {
      if (!current) return current
      const has = current.package_log_types.includes(logType)
      return {
        ...current,
        package_log_types: has
          ? current.package_log_types.filter((lt) => lt !== logType)
          : [...current.package_log_types, logType],
      }
    })
  }, [])

  const openReadiness = openCode && !isNew ? readiness[openCode] : undefined
  const readyCount = useMemo(
    () => configs.filter((c) => readiness[c.code]?.ready).length,
    [configs, readiness],
  )

  return (
    <>
      <header className="page-header">
        <span className="page-eyebrow">Configuration</span>
        <h1>Suppliers</h1>
        <p>
          Every supplier SMF can mock, per environment. Add one here instead of editing Python —
          templates, contract wiring and mutation rules all live on the supplier itself.
        </p>
      </header>

      <div className="banner" style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}>
        <span>⚑</span>
        <span>
          Supplier config is per environment. You're editing <strong>{env}</strong> — switch the
          environment on the right to edit the other one. Dev and staging have separate Backoffice
          supplier records, so their IDs are deliberately different.
        </span>
      </div>

      {loadError && (
        <div className="banner error">
          <span>⚠</span>
          <span>{loadError}</span>
        </div>
      )}

      <section className="recent-panel">
        <div className="recent-header">
          <h2>
            Configured suppliers{' '}
            <span className="hint">
              · {configs.length} in {env}
              {configs.length > 0 && ` · ${readyCount} ready`}
            </span>
          </h2>
          <button type="button" className="btn secondary" onClick={() => openEditor(NEW_CODE)}>
            + Add supplier
          </button>
        </div>

        {loading ? (
          <p className="hint">Loading…</p>
        ) : (
          <div className="supplier-tiles supplier-registry-tiles">
            {configs.map((config) => {
              const label = readinessLabel(readiness[config.code])
              const color = config.ui_color || 'var(--text-muted)'
              return (
                <button
                  type="button"
                  key={config.code}
                  className={`supplier-tile registry-tile${openCode === config.code ? ' on' : ''}`}
                  style={{ ['--tile-color' as string]: color }}
                  onClick={() => openEditor(config.code)}
                  aria-expanded={openCode === config.code}
                >
                  <span className="supplier-tile-header">
                    <span className="code-chip" style={{ ['--sc' as string]: color }}>
                      {config.code}
                    </span>
                    <span className="supplier-tile-body">
                      <strong>{config.name}</strong>
                      <span>
                        {config.supplier_type} · {config.log_types.length} log types
                      </span>
                    </span>
                  </span>
                  <span className="registry-tile-foot">
                    <span className={`ready ${label.cls}`}>
                      <span className="bulb" />
                      {label.text}
                    </span>
                    <span className="hint">
                      {config.supplier_id ? `autoId ${config.auto_id}` : 'not linked'}
                    </span>
                  </span>
                </button>
              )
            })}
            <button type="button" className="tile-add" onClick={() => openEditor(NEW_CODE)}>
              <span style={{ fontSize: '1.3rem' }}>+</span>
              Add supplier
            </button>
          </div>
        )}

        {draft && (
          <div className="inline-editor" ref={editorRef}>
            <header className="inline-editor-head">
              <span
                className="code-chip"
                style={{ ['--sc' as string]: draft.ui_color || 'var(--text-muted)' }}
              >
                {draft.code.trim().toUpperCase() || '???'}
              </span>
              <h3>{isNew ? 'New supplier' : draft.name}</h3>
              <button type="button" className="btn ghost tiny" onClick={closeEditor}>
                Collapse
              </button>
            </header>

            <form onSubmit={handleSave} className="inline-editor-form">
              <div className="wizard-section">
                <div className="wizard-section-title">Identity</div>
                <div className="field-grid">
                  <div className="field">
                    <label>
                      Supplier code
                      <input
                        value={draft.code}
                        onChange={(e) => patch({ code: e.target.value.toUpperCase() })}
                        readOnly={!isNew}
                        maxLength={8}
                        placeholder="AGD"
                        required
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Display name
                      <input
                        value={draft.name}
                        onChange={(e) => patch({ name: e.target.value })}
                        maxLength={64}
                        placeholder="Agoda"
                        required
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Pricing model
                      <select
                        value={draft.supplier_type}
                        onChange={(e) =>
                          patch({ supplier_type: e.target.value as 'net' | 'gross' })
                        }
                      >
                        <option value="net">net</option>
                        <option value="gross">gross</option>
                      </select>
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Colour
                      <input
                        value={draft.ui_color}
                        onChange={(e) => patch({ ui_color: e.target.value })}
                        placeholder="#5b63c9"
                        maxLength={16}
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Supplier currency
                      <input
                        value={draft.default_supplier_currency}
                        onChange={(e) =>
                          patch({ default_supplier_currency: e.target.value.toUpperCase() })
                        }
                        maxLength={3}
                        required
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Contract currency
                      <select
                        value={draft.default_contract_currency}
                        onChange={(e) => patch({ default_contract_currency: e.target.value })}
                      >
                        <option value="USD">USD</option>
                        <option value="EUR">EUR</option>
                        <option value="SAR">SAR</option>
                        <option value="AED">AED</option>
                      </select>
                    </label>
                  </div>
                </div>
              </div>

              <div className="wizard-section">
                <div className="wizard-section-title">
                  Backoffice <span className="hint">{env} environment</span>
                </div>
                <div className="field-grid">
                  <div className="field field-wide">
                    <label>
                      Supplier ID
                      <input
                        value={draft.supplier_id}
                        onChange={(e) => patch({ supplier_id: e.target.value })}
                        placeholder="Mongo _id from GET /api/supplier/summary"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Auto ID
                      <input
                        type="number"
                        value={draft.auto_id || ''}
                        onChange={(e) => patch({ auto_id: Number(e.target.value) || 0 })}
                        placeholder="100006"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Dynamic market type
                      <select
                        value={draft.mock_config.dynamic_market_type ?? ''}
                        onChange={(e) =>
                          patchMock({ dynamic_market_type: e.target.value || null })
                        }
                      >
                        <option value="DynamicMarkupTarget">DynamicMarkupTarget (net)</option>
                        <option value="MarketPriceSource">MarketPriceSource (gross)</option>
                        <option value="">Leave as the reference contract has it</option>
                      </select>
                    </label>
                  </div>
                  <div className="field field-wide">
                    <label>
                      Reference contract ID <span className="hint">cloned for every scenario</span>
                      <input
                        value={draft.reference_contract_id}
                        onChange={(e) => patch({ reference_contract_id: e.target.value })}
                        placeholder="leave empty to build a minimal contract instead"
                      />
                    </label>
                  </div>
                </div>
              </div>

              <div className="wizard-section">
                <div className="wizard-section-title">
                  Mock templates
                  <span className="hint">templates/{draft.code || 'CODE'}/&lt;LogType&gt;/v1.json</span>
                </div>
                {isNew ? (
                  <p className="hint">
                    Save the supplier first, then build its templates from a SID here.
                  </p>
                ) : (
                  <>
                    <div className="sid-ingest">
                      <div className="field">
                        <label>
                          Build from SID
                          <span className="hint">
                            Reads this SID's adapter logs and writes one template per log
                            type, the same way scripts/ingest_sids.py does
                          </span>
                          <input
                            value={sid}
                            onChange={(e) => setSid(e.target.value)}
                            placeholder="e.g. 4471a2c8-…"
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                void handleIngest()
                              }
                            }}
                          />
                        </label>
                      </div>
                      <div className="field">
                        <label>
                          Adapter log source
                          <span className="hint">
                            Substring of the log's <code>source</code> that marks a row as
                            this supplier's — same field as under Mutation rules, saved
                            with the supplier when you build
                          </span>
                          <input
                            value={draft.mutation_config.adapter_source_match}
                            onChange={(e) =>
                              patchMutation({ adapter_source_match: e.target.value })
                            }
                            placeholder="e.g. hotels-derby-bts-adapter"
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault()
                                void handleIngest()
                              }
                            }}
                          />
                        </label>
                      </div>
                      <button
                        type="button"
                        className="btn secondary"
                        onClick={handleIngest}
                        disabled={
                          busy || !sid.trim() || !draft.mutation_config.adapter_source_match.trim()
                        }
                      >
                        {busy ? 'Building…' : 'Build templates'}
                      </button>
                    </div>

                    {ingestError && <p className="error-text">{ingestError}</p>}

                    {ingest && (
                      <div className={`ingest-result${ingest.written.length ? '' : ' empty'}`}>
                        <p>
                          <strong>
                            {ingest.written.length
                              ? `${ingest.written.length} template${ingest.written.length === 1 ? '' : 's'} written`
                              : 'Nothing written'}
                          </strong>
                          {ingest.field_map_paths > 0 &&
                            ` · field map: ${ingest.field_map_paths} paths`}
                          {ingest.unresolved > 0 &&
                            ` · ${ingest.unresolved} row(s) had no resolvable path (see _diagnostics/)`}
                        </p>
                        {ingest.warning && <p className="hint">{ingest.warning}</p>}
                        {ingest.sources_seen.length > 0 && !ingest.written.length && (
                          <>
                            <p className="hint">
                              Adapter sources in this SID — click the right one to use it as
                              the source match, then build again:
                            </p>
                            <span className="ingest-sources">
                              {ingest.sources_seen.map((source) => (
                                <code
                                  key={source}
                                  role="button"
                                  tabIndex={0}
                                  title={`Use "${source}" as ${draft.code}'s adapter log source`}
                                  onClick={() => patchMutation({ adapter_source_match: source })}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter' || e.key === ' ') {
                                      e.preventDefault()
                                      patchMutation({ adapter_source_match: source })
                                    }
                                  }}
                                >
                                  {source}
                                </code>
                              ))}
                            </span>
                          </>
                        )}
                      </div>
                    )}

                    <div className="tpl-list">
                    {ALL_LOG_TYPES.map((logType) => {
                      const served = draft.log_types.includes(logType)
                      const check = openReadiness?.checks.find((c) => c.key === 'templates')
                      const missing =
                        served && check ? check.detail.includes(logType) && !check.ok : false
                      return (
                        <div
                          key={logType}
                          className={`tpl-row${!served ? ' optional' : missing ? ' missing' : ''}`}
                        >
                          <label className="tpl-serve">
                            <input
                              type="checkbox"
                              checked={served}
                              onChange={() => toggleLogType(logType)}
                            />
                            <span className="lt">{logType}</span>
                          </label>
                          <label
                            className="tpl-mutate"
                            title="Mutate packages in this response (prices, board, room names)"
                          >
                            <input
                              type="checkbox"
                              checked={draft.package_log_types.includes(logType)}
                              disabled={!served}
                              onChange={() => togglePackageLogType(logType)}
                            />
                            mutate
                          </label>
                          <span className="ready-slot">
                            {!served ? (
                              <span className="hint">not served</span>
                            ) : missing ? (
                              <span className="ready bad">
                                <span className="bulb" />
                                missing
                              </span>
                            ) : (
                              <span className="ready ok">
                                <span className="bulb" />
                                on disk
                              </span>
                            )}
                          </span>
                          <label className="btn ghost tiny tpl-upload">
                            {missing ? 'Upload JSON' : 'Replace'}
                            <input
                              type="file"
                              accept="application/json,.json"
                              hidden
                              disabled={!served || busy}
                              onChange={(e) => {
                                const file = e.target.files?.[0]
                                e.target.value = ''
                                if (file) void handleTemplateUpload(logType, file)
                              }}
                            />
                          </label>
                        </div>
                      )
                    })}
                    </div>
                    <p className="hint" style={{ marginTop: '0.6rem' }}>
                      No SID to hand? Upload a MockServer expectation JSON per log type
                      with the buttons above.
                    </p>
                  </>
                )}
              </div>

              <div className="wizard-section">
                <div className="wizard-section-title">Request paths</div>
                <div className="field-grid">
                  <div className="field">
                    <label>
                      Contract URL source
                      <select
                        value={draft.mock_config.opt_source}
                        onChange={(e) =>
                          patchMock({ opt_source: e.target.value as 'canonical' | 'ingested' })
                        }
                      >
                        <option value="ingested">From the templates' own paths</option>
                        <option value="canonical">From the canonical paths below</option>
                      </select>
                    </label>
                  </div>
                  <div className="field">
                    <label className="checkbox-field">
                      <input
                        type="checkbox"
                        checked={draft.mock_config.path_rewrite}
                        onChange={(e) => patchMock({ path_rewrite: e.target.checked })}
                      />
                      Pin mocks to canonical paths
                    </label>
                  </div>
                  <div className="field">
                    <label className="checkbox-field">
                      <input
                        type="checkbox"
                        checked={draft.mock_config.path_namespaced}
                        onChange={(e) => patchMock({ path_namespaced: e.target.checked })}
                      />
                      Isolate paths per scenario
                    </label>
                  </div>
                  <div className="field field-wide">
                    <label>
                      Canonical base per log type <span className="hint">JSON</span>
                      <textarea
                        rows={4}
                        value={JSON.stringify(draft.mock_config.canonical_base, null, 2)}
                        onChange={(e) => {
                          try {
                            patchMock({ canonical_base: JSON.parse(e.target.value) })
                          } catch {
                            /* keep typing — validated on save */
                          }
                        }}
                        placeholder={'{\n  "Search": "/api/v1/distribution"\n}'}
                      />
                    </label>
                  </div>
                  <div className="field field-wide">
                    <label>
                      Path suffix per log type <span className="hint">disambiguates shared paths</span>
                      <textarea
                        rows={4}
                        value={JSON.stringify(draft.mock_config.mock_path_suffix, null, 2)}
                        onChange={(e) => {
                          try {
                            patchMock({ mock_path_suffix: JSON.parse(e.target.value) })
                          } catch {
                            /* keep typing */
                          }
                        }}
                        placeholder={'{\n  "Search": "search"\n}'}
                      />
                    </label>
                  </div>
                  <div className="field field-wide">
                    <label>
                      Contract opt field per log type
                      <textarea
                        rows={4}
                        value={JSON.stringify(draft.mock_config.opt_field_map, null, 2)}
                        onChange={(e) => {
                          try {
                            patchMock({ opt_field_map: JSON.parse(e.target.value) })
                          } catch {
                            /* keep typing */
                          }
                        }}
                        placeholder={'{\n  "Search": "searchUrl"\n}'}
                      />
                    </label>
                  </div>
                </div>
              </div>

              <div className="wizard-section">
                <div className="wizard-section-title">
                  Mutation rules
                  {!isNew && (
                    <button
                      type="button"
                      className="btn ghost tiny"
                      onClick={handleGenerateFieldMap}
                      disabled={busy}
                    >
                      Generate field map from templates
                    </button>
                  )}
                </div>
                <div className="field-grid">
                  <div className="field field-wide">
                    <label>
                      Packages array path
                      <span className="hint">
                        the array of rates cloned to the requested package count
                      </span>
                      <input
                        value={draft.mutation_config.packages_path}
                        onChange={(e) => patchMutation({ packages_path: e.target.value })}
                        placeholder="httpResponse.body.body.0.accommodations"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Price keys
                      <input
                        value={draft.mutation_config.price_keys.join(', ')}
                        onChange={(e) => patchMutation({ price_keys: splitKeys(e.target.value) })}
                        placeholder="totalPrice, netPrice"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Board key
                      <input
                        value={draft.mutation_config.board_key}
                        onChange={(e) => patchMutation({ board_key: e.target.value })}
                        placeholder="board"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Room name key
                      <input
                        value={draft.mutation_config.room_name_key}
                        onChange={(e) => patchMutation({ room_name_key: e.target.value })}
                        placeholder="roomName"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Currency key
                      <input
                        value={draft.mutation_config.currency_key}
                        onChange={(e) => patchMutation({ currency_key: e.target.value })}
                        placeholder="currency"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Hotel ID key
                      <input
                        value={draft.mutation_config.hotel_id_key}
                        onChange={(e) => patchMutation({ hotel_id_key: e.target.value })}
                        placeholder="hotelId"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Package ID key
                      <input
                        value={draft.mutation_config.package_id_key}
                        onChange={(e) => patchMutation({ package_id_key: e.target.value })}
                        placeholder="id"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Check-in keys
                      <input
                        value={draft.mutation_config.check_in_keys.join(', ')}
                        onChange={(e) => patchMutation({ check_in_keys: splitKeys(e.target.value) })}
                        placeholder="checkInDate, checkin"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Check-out keys
                      <input
                        value={draft.mutation_config.check_out_keys.join(', ')}
                        onChange={(e) =>
                          patchMutation({ check_out_keys: splitKeys(e.target.value) })
                        }
                        placeholder="checkOutDate, checkout"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Allowed board codes
                      <input
                        value={draft.mutation_config.board_values.join(', ')}
                        onChange={(e) => patchMutation({ board_values: splitKeys(e.target.value) })}
                        placeholder="RO, BB, HB, FB, AI"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Adapter log source match
                      <input
                        value={draft.mutation_config.adapter_source_match}
                        onChange={(e) => patchMutation({ adapter_source_match: e.target.value })}
                        placeholder="extranet"
                      />
                    </label>
                  </div>
                  <div className="field">
                    <label>
                      Booking ID format
                      <select
                        value={draft.mutation_config.booking_id_format}
                        onChange={(e) =>
                          patchMutation({
                            booking_id_format: e.target
                              .value as SupplierConfigPayload['mutation_config']['booking_id_format'],
                          })
                        }
                      >
                        <option value="digits">Digits, same length</option>
                        <option value="prefix_digits">Keep PREFIX-, renumber</option>
                        <option value="prefix_hex">Keep prefix, append hex</option>
                      </select>
                    </label>
                  </div>
                </div>
              </div>

              {!isNew && openReadiness && (
                <div className="wizard-section">
                  <div className="wizard-section-title">
                    Before this supplier can build a scenario
                  </div>
                  <div className="checks">
                    {openReadiness.checks.map((check) => (
                      <div
                        key={check.key}
                        className={`check ${!check.blocking ? 'info' : check.ok ? 'ok' : 'bad'}`}
                      >
                        <span className="mk">
                          {!check.blocking ? (check.ok ? '◆' : '◇') : check.ok ? '✔' : '✖'}
                        </span>
                        <span className="lbl">
                          {check.label}
                          <small>{check.detail}</small>
                        </span>
                        <span />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {probe && (
                <div className="wizard-section">
                  <div className="wizard-section-title">
                    Test scenario result
                    <span className="hint">
                      {probe.plugin === 'generic'
                        ? 'generic mutator'
                        : `custom plugin · ${probe.plugin}`}
                    </span>
                  </div>
                  {probe.error ? (
                    <p className="error-text">{probe.error}</p>
                  ) : (
                    <div className="tpl-list">
                      {probe.log_types.map((result) => (
                        <div
                          key={result.log_type}
                          className={`tpl-row${result.ok ? '' : ' missing'}`}
                        >
                          <span className="lt">{result.log_type}</span>
                          <span className="sz">{result.path ?? result.error ?? ''}</span>
                          <span className={`ready ${result.ok ? 'ok' : 'bad'}`}>
                            <span className="bulb" />
                            {result.ok ? 'built' : 'failed'}
                          </span>
                          <span />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {formError && <p className="error-text">{formError}</p>}
              {notice && !formError && (
                <p className="hint" style={{ color: 'var(--success)' }}>
                  {notice}
                </p>
              )}

              <div className="detail-footer">
                {!isNew && (
                  <button
                    type="button"
                    className="btn danger tiny"
                    onClick={handleDelete}
                    disabled={busy}
                  >
                    Delete supplier
                  </button>
                )}
                <span className="spacer" />
                {!isNew && (
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={handleProbe}
                    disabled={busy}
                  >
                    Test scenario
                  </button>
                )}
                <button type="submit" className="btn primary" disabled={busy}>
                  {busy ? 'Saving…' : isNew ? 'Add supplier' : 'Save supplier'}
                </button>
              </div>
            </form>
          </div>
        )}
      </section>
    </>
  )
}
