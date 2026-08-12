import { API_BASE } from './base'

export interface ApiTemplatePackageRow {
  room_name: string
  room_basis: string
  price: number
  refundable: boolean
}

export interface ApiSupplierTemplatePackages {
  supplier: string
  supplier_currency: string
  contract_currency: string
  packages: ApiTemplatePackageRow[]
  assignment_target?: 'apikey' | 'sbgroup' | 'both'
}

export interface ApiScenarioTemplate {
  id: string
  label: string
  description: string
  atg_hotel_id: string
  suppliers: ApiSupplierTemplatePackages[]
  sb_enabled?: boolean
  created_at: string
  has_br_child_condition?: boolean
}

export interface ScenarioTemplateCreatePayload {
  label: string
  description?: string
  atg_hotel_id: string
  suppliers: ApiSupplierTemplatePackages[]
  sb_enabled?: boolean
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
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
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listScenarioTemplates(): Promise<ApiScenarioTemplate[]> {
  return request('/api/scenario-templates')
}

export function createScenarioTemplate(payload: ScenarioTemplateCreatePayload): Promise<ApiScenarioTemplate> {
  return request('/api/scenario-templates', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateScenarioTemplate(
  id: string,
  payload: ScenarioTemplateCreatePayload,
): Promise<ApiScenarioTemplate> {
  return request(`/api/scenario-templates/${id}`, { method: 'PUT', body: JSON.stringify(payload) })
}

export function deleteScenarioTemplate(id: string): Promise<void> {
  return request(`/api/scenario-templates/${id}`, { method: 'DELETE' })
}
