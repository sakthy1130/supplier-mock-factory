import { API_BASE } from './base'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  })
  if (!response.ok) {
    const body = await response.text()
    let detail = body
    try {
      const json = JSON.parse(body) as { detail?: string }
      detail = json.detail ?? body
    } catch {
      /* use raw body */
    }
    throw new Error(detail || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function getHealth() {
  return request<{ status: string; service: string; phase: string }>('/health')
}

export function listSuppliers() {
  return request<{ code: string; name: string; log_types: string[]; status: string }[]>(
    '/api/suppliers',
  )
}

export {
  clearAllScenarios,
  createScenario,
  getScenarioQuickwitLogs,
  listScenarios,
  getScenario,
  refreshBookingIds,
  teardownScenario,
} from './scenarios'
