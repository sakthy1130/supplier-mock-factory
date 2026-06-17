import { API_BASE } from './base'
import type { TestRunState } from '../types/testRun'

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    const body = await response.text()
    throw new Error(`GET ${path} → ${response.status}: ${body}`)
  }
  return response.json() as Promise<T>
}

/** GET /api/test-run — list all runs */
export async function listTestRuns(): Promise<TestRunState[]> {
  return get<TestRunState[]>('/api/test-run')
}

/** GET /api/test-run/{runId}/status — single run state */
export async function getTestRunState(runId: string): Promise<TestRunState> {
  return get<TestRunState>(`/api/test-run/${runId}/status`)
}
