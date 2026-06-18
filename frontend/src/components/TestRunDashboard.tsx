import { useCallback, useEffect, useRef, useState } from 'react'
import { listTestRuns, getTestRunState } from '../api/testRun'
import type { StepNode, TestResult, TestRunState, TestStatus } from '../types/testRun'

const POLL_MS = 2000

// ------------------------------------------------------------------
// Colour helpers
// ------------------------------------------------------------------
const STATUS_COLOR: Record<TestStatus, string> = {
  PASSED: '#22c55e',
  FAILED: '#ef4444',
  SKIPPED: '#f59e0b',
  ABORTED: '#6b7280',
}

const RUN_COLOR: Record<string, string> = {
  RUNNING: '#3b82f6',
  COMPLETE: '#22c55e',
  ABORTED: '#6b7280',
}

function statusBadge(status: string, color: string) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 700,
        letterSpacing: '0.05em',
        background: `${color}22`,
        color,
        border: `1px solid ${color}55`,
      }}
    >
      {status}
    </span>
  )
}

function formatMs(ms: number) {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function shortClass(fqn: string) {
  const parts = fqn.split('.')
  return parts[parts.length - 1] ?? fqn
}

// ------------------------------------------------------------------
// Suite labelling — the /test-run backend is generic, so a single run list
// mixes Smart Booking and Crawla runs. Derive a suite label per run from its
// test classes so the dashboard distinguishes them at a glance.
// ------------------------------------------------------------------
const SUITE_COLOR: Record<string, string> = {
  'Smart Booking': '#8b5cf6',
  Crawla: '#06b6d4',
  Other: '#6b7280',
}

function suiteOf(testClass: string): string {
  const name = shortClass(testClass)
  if (/crawla/i.test(name)) return 'Crawla'
  if (/^sb|smartbook/i.test(name)) return 'Smart Booking'
  return 'Other'
}

function runSuites(results: TestResult[]): string[] {
  const seen = new Set<string>()
  for (const r of results) seen.add(suiteOf(r.test_class))
  return [...seen]
}

function suiteBadge(suite: string) {
  const color = SUITE_COLOR[suite] ?? SUITE_COLOR.Other
  return (
    <span
      key={suite}
      style={{
        display: 'inline-block',
        padding: '1px 7px',
        borderRadius: 10,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.04em',
        background: `${color}22`,
        color,
        border: `1px solid ${color}55`,
      }}
    >
      {suite}
    </span>
  )
}

// ------------------------------------------------------------------
// Allure @Step tree (recursive)
// ------------------------------------------------------------------
const STEP_ICON: Record<string, { icon: string; color: string }> = {
  PASSED: { icon: '✓', color: '#22c55e' },
  FAILED: { icon: '✗', color: '#ef4444' },
  BROKEN: { icon: '✗', color: '#ef4444' },
  SKIPPED: { icon: '⊘', color: '#f59e0b' },
}

function StepTree({ steps, depth = 0 }: { steps: StepNode[]; depth?: number }) {
  return (
    <div>
      {steps.map((step, i) => {
        const s = STEP_ICON[(step.status ?? '').toUpperCase()] ?? { icon: '•', color: '#8b949e' }
        return (
          <div key={i}>
            <div
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 8,
                padding: '2px 0',
                paddingLeft: 12 + depth * 16,
                fontFamily: 'monospace',
                fontSize: 12,
                borderBottom: '1px solid #161b22',
              }}
            >
              <span style={{ color: s.color, width: 12, flexShrink: 0 }}>{s.icon}</span>
              <span style={{ color: '#c9d1d9', flex: 1, wordBreak: 'break-word' }}>{step.name}</span>
              <span style={{ color: '#6b7280', flexShrink: 0 }}>{formatMs(step.duration_ms)}</span>
            </div>
            {step.steps && step.steps.length > 0 && <StepTree steps={step.steps} depth={depth + 1} />}
          </div>
        )
      })}
    </div>
  )
}

// ------------------------------------------------------------------
// Result row with expandable failure details
// ------------------------------------------------------------------
function ResultRow({ result }: { result: TestResult }) {
  const [open, setOpen] = useState(false)
  const color = STATUS_COLOR[result.status]
  const hasFail = !!(result.failure_message || result.stack_trace || result.http_details)
  // Passed/skipped tests still carry the provisioning log + scenario id — make every
  // row with any detail expandable, not just failures.
  const hasSteps = (result.steps?.length ?? 0) > 0
  const hasDetail = hasFail || hasSteps || (result.provisioning_log?.length ?? 0) > 0 || !!result.scenario_id

  return (
    <>
      <tr
        style={{
          cursor: hasDetail ? 'pointer' : 'default',
          background: open ? '#1a1a2e' : 'transparent',
        }}
        onClick={() => hasDetail && setOpen((v) => !v)}
      >
        <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 13 }}>
          {shortClass(result.test_class)}
        </td>
        <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontSize: 13 }}>
          {result.test_method}
        </td>
        <td style={{ padding: '8px 12px' }}>{statusBadge(result.status, color)}</td>
        <td style={{ padding: '8px 12px', color: '#9ca3af', fontSize: 12 }}>
          {formatMs(result.duration_ms)}
        </td>
        <td style={{ padding: '8px 12px', color: '#9ca3af', fontSize: 12 }}>
          {result.posted_at ? new Date(result.posted_at).toLocaleTimeString() : '—'}
        </td>
        <td style={{ padding: '8px 12px', fontSize: 12, color: '#6b7280' }}>
          {hasDetail ? (open ? '▲ hide' : '▼ details') : ''}
        </td>
      </tr>
      {open && hasDetail && (
        <tr>
          <td
            colSpan={6}
            style={{ padding: '0 12px 16px 12px', background: '#0f0f1a' }}
          >
            {result.scenario_id && (
              <div style={{ margin: '8px 0' }}>
                <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>SCENARIO</div>
                <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#93c5fd' }}>
                  {result.scenario_id}
                </div>
              </div>
            )}

            {hasSteps && (
              <details open style={{ margin: '8px 0' }}>
                <summary
                  style={{
                    fontSize: 11,
                    color: '#60a5fa',
                    cursor: 'pointer',
                    marginBottom: 4,
                    fontWeight: 600,
                  }}
                >
                  Steps ({result.steps!.length})
                </summary>
                <div
                  style={{
                    background: '#0d1117',
                    border: '1px solid #1d3a5c',
                    borderRadius: 4,
                    padding: '4px 0',
                    maxHeight: 360,
                    overflow: 'auto',
                  }}
                >
                  <StepTree steps={result.steps!} />
                </div>
              </details>
            )}
            {result.failure_message && (
              <div style={{ margin: '8px 0' }}>
                <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>FAILURE MESSAGE</div>
                <pre
                  style={{
                    margin: 0,
                    padding: '8px 12px',
                    background: '#1a0a0a',
                    borderLeft: '3px solid #ef4444',
                    color: '#fca5a5',
                    fontSize: 12,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    borderRadius: 4,
                  }}
                >
                  {result.failure_message}
                </pre>
              </div>
            )}

            {result.http_details && (
              <div style={{ margin: '8px 0' }}>
                <div style={{ fontSize: 11, color: '#9ca3af', marginBottom: 4 }}>LAST HTTP CALL</div>
                <div
                  style={{
                    padding: '8px 12px',
                    background: '#0d1117',
                    border: '1px solid #30363d',
                    borderRadius: 4,
                    fontSize: 12,
                    fontFamily: 'monospace',
                    color: '#e6edf3',
                  }}
                >
                  <div style={{ color: '#79c0ff', marginBottom: 4 }}>
                    {result.http_details.method} {result.http_details.url}
                    <span
                      style={{
                        marginLeft: 12,
                        color:
                          result.http_details.response_status >= 400 ? '#f85149' : '#3fb950',
                      }}
                    >
                      {result.http_details.response_status}
                    </span>
                  </div>
                  {result.http_details.request_body && (
                    <details>
                      <summary style={{ color: '#8b949e', cursor: 'pointer', marginBottom: 4 }}>
                        Request body
                      </summary>
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          color: '#c9d1d9',
                          margin: 0,
                        }}
                      >
                        {result.http_details.request_body}
                      </pre>
                    </details>
                  )}
                  {result.http_details.response_body && (
                    <details>
                      <summary style={{ color: '#8b949e', cursor: 'pointer', marginBottom: 4 }}>
                        Response body
                      </summary>
                      <pre
                        style={{
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                          color: '#c9d1d9',
                          margin: 0,
                        }}
                      >
                        {result.http_details.response_body}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            )}

            {result.stack_trace && (
              <details>
                <summary
                  style={{
                    fontSize: 11,
                    color: '#9ca3af',
                    cursor: 'pointer',
                    margin: '8px 0 4px',
                  }}
                >
                  Stack trace
                </summary>
                <pre
                  style={{
                    margin: 0,
                    padding: '8px 12px',
                    background: '#0d1117',
                    border: '1px solid #30363d',
                    color: '#8b949e',
                    fontSize: 11,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                    borderRadius: 4,
                    maxHeight: 300,
                    overflow: 'auto',
                  }}
                >
                  {result.stack_trace}
                </pre>
              </details>
            )}

            {result.provisioning_log && result.provisioning_log.length > 0 && (
              <details open>
                <summary
                  style={{
                    fontSize: 11,
                    color: '#60a5fa',
                    cursor: 'pointer',
                    margin: '8px 0 4px',
                    fontWeight: 600,
                  }}
                >
                  Provisioning Log ({result.provisioning_log.length} steps)
                </summary>
                <div
                  style={{
                    padding: '8px 12px',
                    background: '#0d1117',
                    border: '1px solid #1d3a5c',
                    borderRadius: 4,
                    fontSize: 11,
                    fontFamily: 'monospace',
                    maxHeight: 320,
                    overflow: 'auto',
                  }}
                >
                  {result.provisioning_log.map((line, i) => (
                    <div
                      key={i}
                      style={{
                        color: line.startsWith('[apiKey') || line.startsWith('[sb') || line.startsWith('[cache') ? '#93c5fd' : '#8b949e',
                        borderBottom: '1px solid #1f2937',
                        padding: '3px 0',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-all',
                      }}
                    >
                      {line}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

// ------------------------------------------------------------------
// Progress bar
// ------------------------------------------------------------------
function ProgressBar({ passed, failed, skipped, total }: { passed: number; failed: number; skipped: number; total: number }) {
  const done = passed + failed + skipped
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div style={{ margin: '12px 0' }}>
      <div
        style={{
          height: 8,
          borderRadius: 4,
          background: '#1f2937',
          overflow: 'hidden',
          display: 'flex',
        }}
      >
        <div style={{ width: `${total > 0 ? (passed / total) * 100 : 0}%`, background: '#22c55e', transition: 'width 0.3s' }} />
        <div style={{ width: `${total > 0 ? (failed / total) * 100 : 0}%`, background: '#ef4444', transition: 'width 0.3s' }} />
        <div style={{ width: `${total > 0 ? (skipped / total) * 100 : 0}%`, background: '#f59e0b', transition: 'width 0.3s' }} />
      </div>
      <div style={{ fontSize: 11, color: '#6b7280', marginTop: 4 }}>
        {done}/{total} ({pct}%) — {passed} passed · {failed} failed · {skipped} skipped
      </div>
    </div>
  )
}

// ------------------------------------------------------------------
// Single run panel
// ------------------------------------------------------------------
function RunPanel({ runId }: { runId: string }) {
  const [state, setState] = useState<TestRunState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchState = useCallback(async () => {
    try {
      const s = await getTestRunState(runId)
      setState(s)
      if (s.status !== 'RUNNING') {
        if (pollRef.current) clearInterval(pollRef.current)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Fetch failed')
    }
  }, [runId])

  useEffect(() => {
    fetchState()
    pollRef.current = setInterval(fetchState, POLL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [fetchState])

  if (error) return <div style={{ color: '#ef4444', padding: 16 }}>{error}</div>
  if (!state) return <div style={{ color: '#6b7280', padding: 16 }}>Loading…</div>

  const runColor = RUN_COLOR[state.status] ?? '#9ca3af'

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        {statusBadge(state.status, runColor)}
        <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#6b7280' }}>
          {state.run_id}
        </span>
        {runSuites(state.results).map(suiteBadge)}
        {state.status === 'RUNNING' && (
          <span style={{ fontSize: 12, color: '#3b82f6' }}>● live</span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 12, color: '#6b7280' }}>
          Started {new Date(state.started_at).toLocaleTimeString()}
          {state.completed_at && ` · Ended ${new Date(state.completed_at).toLocaleTimeString()}`}
        </span>
      </div>

      <ProgressBar
        passed={state.passed}
        failed={state.failed}
        skipped={state.skipped}
        total={state.total}
      />

      {/* Results table */}
      {state.results.length === 0 ? (
        <div style={{ color: '#6b7280', fontSize: 13, marginTop: 16 }}>
          Waiting for test results…
        </div>
      ) : (
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: 13,
            marginTop: 16,
          }}
        >
          <thead>
            <tr style={{ borderBottom: '1px solid #1f2937' }}>
              {['Class', 'Method', 'Status', 'Duration', 'Time', ''].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: '6px 12px',
                    textAlign: 'left',
                    fontSize: 11,
                    fontWeight: 600,
                    color: '#6b7280',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {state.results.map((r, i) => (
              <ResultRow key={`${r.test_class}-${r.test_method}-${i}`} result={r} />
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ------------------------------------------------------------------
// Main dashboard — lists all runs, selects active one
// ------------------------------------------------------------------
export function TestRunDashboard() {
  const [runs, setRuns] = useState<TestRunState[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadRuns = useCallback(async () => {
    try {
      const all = await listTestRuns()
      const sorted = [...all].sort(
        (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime(),
      )
      setRuns(sorted)
      // Auto-select the most recent RUNNING run, or the first one if nothing selected
      const running = sorted.find((r) => r.status === 'RUNNING')
      setSelectedRunId((prev) => {
        if (prev) return prev
        return running?.run_id ?? sorted[0]?.run_id ?? null
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load runs')
    } finally {
      setLoading(false)
    }
  }, [])

  // Auto-select running run when a new one appears
  useEffect(() => {
    loadRuns()
    const id = setInterval(loadRuns, POLL_MS * 5)  // refresh list every 10s
    return () => clearInterval(id)
  }, [loadRuns])

  return (
    <div style={{ display: 'flex', height: '100%', gap: 0 }}>
      {/* Sidebar — run list */}
      <div
        style={{
          width: 260,
          flexShrink: 0,
          borderRight: '1px solid #1f2937',
          overflowY: 'auto',
          padding: '16px 0',
        }}
      >
        <div
          style={{
            padding: '0 16px 12px',
            fontSize: 11,
            fontWeight: 700,
            color: '#6b7280',
            textTransform: 'uppercase',
            letterSpacing: '0.07em',
          }}
        >
          Test Runs
        </div>
        {loading && (
          <div style={{ color: '#6b7280', fontSize: 13, padding: '0 16px' }}>Loading…</div>
        )}
        {error && (
          <div style={{ color: '#ef4444', fontSize: 13, padding: '0 16px' }}>{error}</div>
        )}
        {!loading && runs.length === 0 && (
          <div style={{ color: '#6b7280', fontSize: 13, padding: '0 16px' }}>
            No test runs yet. Run the Java test suite to see results here.
          </div>
        )}
        {runs.map((run) => {
          const color = RUN_COLOR[run.status] ?? '#9ca3af'
          const isSelected = run.run_id === selectedRunId
          return (
            <button
              key={run.run_id}
              type="button"
              onClick={() => setSelectedRunId(run.run_id)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                background: isSelected ? '#1a2332' : 'transparent',
                border: 'none',
                borderLeft: isSelected ? `3px solid ${color}` : '3px solid transparent',
                padding: '10px 16px',
                cursor: 'pointer',
                color: 'inherit',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#9ca3af' }}>
                  {run.run_id.slice(0, 8)}…
                </span>
                {statusBadge(run.status, color)}
              </div>
              {runSuites(run.results).length > 0 && (
                <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {runSuites(run.results).map(suiteBadge)}
                </div>
              )}
              <div style={{ marginTop: 4, fontSize: 11, color: '#6b7280' }}>
                {new Date(run.started_at).toLocaleString()}
              </div>
              <div style={{ marginTop: 4, fontSize: 12, color: '#9ca3af' }}>
                <span style={{ color: '#22c55e' }}>{run.passed}✓</span>
                {' · '}
                <span style={{ color: '#ef4444' }}>{run.failed}✗</span>
                {' · '}
                <span style={{ color: '#f59e0b' }}>{run.skipped}⊘</span>
                {' · '}
                {run.total} total
              </div>
            </button>
          )
        })}
      </div>

      {/* Main panel */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 24px' }}>
        {!selectedRunId ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              height: '60%',
              color: '#6b7280',
              gap: 12,
            }}
          >
            <div style={{ fontSize: 32 }}>◎</div>
            <p style={{ margin: 0, fontSize: 14 }}>Select a test run from the list</p>
          </div>
        ) : (
          <RunPanel key={selectedRunId} runId={selectedRunId} />
        )}
      </div>
    </div>
  )
}
