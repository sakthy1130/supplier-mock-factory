import { API_BASE, formatApiError } from './base'

export interface ApiTemplatePackageRow {
  room_name: string
  room_basis: string
  price: number
  refundable: boolean
  /** EXP explicit pricing, both or neither: price = original_price_with_vat + markup. */
  original_price_with_vat?: number
  markup?: number
}

export interface ApiSupplierTemplatePackages {
  supplier: string
  supplier_currency: string
  contract_currency: string
  packages: ApiTemplatePackageRow[]
  assignment_target?: 'apikey' | 'sbgroup' | 'both'
  /** Per supplier, matching PackageSpec — one price check per supplier, not per row. */
  prebooking_status?: 'available' | 'price_changed' | 'sold_out'
  prebooking_changed_price?: number | null
  can_prebook?: boolean | null
  prebook_url?: boolean | null
  /** Which package the booking flow is built for; without it a template made from a
   *  bookable scenario would run to packages only. */
  booking_package_index?: number | null
  adults?: number
  child_ages?: number[]
  room_count?: number
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
  /** Which Templates tab this belongs under; absent reads as bedding. */
  function?: string | null
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
    throw new Error(formatApiError(await response.text(), response.status))
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

/** Which Templates tab a saved template belongs under. */
export type TemplateKind = 'templateBeddingMock' | 'preBookingMock'

export const TEMPLATE_KIND_BEDDING: TemplateKind = 'templateBeddingMock'
export const TEMPLATE_KIND_PREBOOKING: TemplateKind = 'preBookingMock'

/** Templates saved before the two kinds existed carry no function — they are all
 *  bedding mocks, so that is what an absent or unrecognised value reads as. */
export function templateKind(fn: string | null | undefined): TemplateKind {
  return fn === TEMPLATE_KIND_PREBOOKING ? TEMPLATE_KIND_PREBOOKING : TEMPLATE_KIND_BEDDING
}

export function saveScenarioAsTemplate(
  scenarioId: string,
  payload: { label: string; description?: string; function?: TemplateKind },
): Promise<ApiScenarioTemplate> {
  return request<ApiScenarioTemplate>(`/api/scenario-templates/from-scenario/${scenarioId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function saveRequestAsTemplate(payload: {
  label: string
  description?: string
  function?: TemplateKind
  request: Record<string, unknown>
}): Promise<ApiScenarioTemplate> {
  return request<ApiScenarioTemplate>('/api/scenario-templates/from-request', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateScenarioTemplateFromRequest(
  id: string,
  payload: {
    label: string
    description?: string
    function?: TemplateKind
    request: Record<string, unknown>
  },
): Promise<ApiScenarioTemplate> {
  return request<ApiScenarioTemplate>(`/api/scenario-templates/${id}/from-request`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
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
