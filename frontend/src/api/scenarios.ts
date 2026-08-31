import type { ScenarioBundle, ScenarioListItem, ScenarioRequest } from '../types/scenario'
import type { CrawlaScenarioRunResult } from '../types/crawla'
import type { QuickwitSearchResponse } from '../types/quickwit'
import { API_BASE, envHeaders, formatApiError } from './base'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
      ...envHeaders(),
    },
  })
  if (!response.ok) {
    throw new Error(formatApiError(await response.text(), response.status))
  }
  return response.json() as Promise<T>
}

export function createScenario(payload: ScenarioRequest) {
  return request<ScenarioBundle>('/api/scenarios', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listScenarios() {
  return request<ScenarioListItem[]>('/api/scenarios')
}

export function getScenario(id: string) {
  return request<ScenarioBundle>(`/api/scenarios/${id}`)
}

/** How far a run drives the core. Chosen per run, not baked into the scenario. */
export type RunMode = 'packages' | 'e2e'

export function runScenario(id: string, mode: RunMode = 'e2e') {
  return request<CrawlaScenarioRunResult>(`/api/scenarios/${id}/run?mode=${mode}`, {
    method: 'POST',
  })
}

export function refreshBookingIds(id: string) {
  return request<ScenarioBundle>(`/api/scenarios/${id}/refresh-booking-ids`, {
    method: 'POST',
  })
}

export function teardownScenario(id: string) {
  return request<ScenarioBundle>(`/api/scenarios/${id}`, { method: 'DELETE' })
}

export function clearAllScenarios() {
  return request<{ queued: number; scenario_ids: string[] }>('/api/scenarios/all', {
    method: 'DELETE',
  })
}

export function getScenarioQuickwitLogs(id: string, minutes = 60, maxHits = 200) {
  const params = new URLSearchParams({
    minutes: String(minutes),
    max_hits: String(maxHits),
  })
  return request<QuickwitSearchResponse>(`/api/scenarios/${id}/quickwit-logs?${params.toString()}`)
}
