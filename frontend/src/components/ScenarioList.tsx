import type { ScenarioListItem } from '../types/scenario'

interface Props {
  items: ScenarioListItem[]
  selectedId: string | null
  onSelect: (id: string) => void
  onClear: (item: ScenarioListItem) => void
  onRefresh: () => void
  loading: boolean
  clearingIds?: Set<string>
}

function statusClass(status: string) {
  return `status-pill status-${status.toLowerCase().replace(/_/g, '-')}`
}

function formatStatus(status: string) {
  return status.replace(/_/g, ' ')
}

export function ScenarioList({ items, selectedId, onSelect, onClear, onRefresh, loading, clearingIds = new Set() }: Props) {
  return (
    <div className="list-panel">
      <div className="list-header">
        <h2 style={{ fontSize: '1.05rem', fontWeight: 600, color: 'var(--text-strong)' }}>
          All scenarios
        </h2>
        <button type="button" className="btn ghost" onClick={onRefresh} disabled={loading}>
          {loading ? '…' : '↻ Refresh'}
        </button>
      </div>

      {items.length === 0 ? (
        <div className="empty-state">
          <div className="empty-state-icon">∅</div>
          <p>No scenarios yet</p>
          <p className="hint" style={{ marginTop: '0.35rem' }}>
            Create your first mock from the wizard
          </p>
        </div>
      ) : (
        <ul className="scenario-list">
          {items.map((item) => (
            <li key={item.id}>
              <div className={['list-row', selectedId === item.id ? 'selected' : ''].filter(Boolean).join(' ')}>
                <button
                  type="button"
                  className="list-item"
                  onClick={() => onSelect(item.id)}
                  disabled={clearingIds.has(item.id)}
                >
                  <div className="list-item-top">
                    <span className="list-ns">{item.namespace}</span>
                    <span className={statusClass(item.status)}>{formatStatus(item.status)}</span>
                  </div>
                  <span className="list-meta">
                    {item.suppliers.join(' · ')}
                    {item.created_at && ` · ${new Date(item.created_at).toLocaleString()}`}
                  </span>
                </button>
                <button
                  type="button"
                  className="btn danger list-clear"
                  onClick={() => onClear(item)}
                  disabled={clearingIds.has(item.id)}
                  title="Clear mocks, contracts, apiKey, BR setup, and remove this scenario from history"
                >
                  {clearingIds.has(item.id) ? 'Clearing…' : 'Clear'}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
