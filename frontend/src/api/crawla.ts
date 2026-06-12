import { API_BASE } from './base'
import type {
  CrawlaAnchorPackagesResponse,
  CrawlaAnchorRequest,
  CrawlaAnchorSearchResponse,
  CrawlaScenarioRunResult,
  CrawlaScenarioRequest,
} from '../types/crawla'
import type { ScenarioBundle } from '../types/scenario'

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

export function fetchCrawlaSearchAnchor(payload: CrawlaAnchorRequest) {
  return request<CrawlaAnchorSearchResponse>('/api/crawla/anchor/search', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function fetchCrawlaPackagesAnchor(payload: CrawlaAnchorRequest) {
  return request<CrawlaAnchorPackagesResponse>('/api/crawla/anchor/packages', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function createCrawlaScenario(payload: CrawlaScenarioRequest) {
  return request<ScenarioBundle>('/api/crawla/scenarios', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function runCrawlaScenario(scenarioId: string) {
  return request<CrawlaScenarioRunResult>(`/api/crawla/scenarios/${scenarioId}/run`, {
    method: 'POST',
  })
}
