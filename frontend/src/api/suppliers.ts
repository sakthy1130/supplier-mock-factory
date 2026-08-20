import { API_BASE, envHeaders } from './base'

export interface ApiMockConfig {
  canonical_base: Record<string, string>
  mock_path_suffix: Record<string, string>
  opt_field_map: Record<string, string>
  opt_source: 'canonical' | 'ingested'
  path_rewrite: boolean
  path_namespaced: boolean
  unwrap_adapter_log_body: boolean
  opt_defaults: Record<string, unknown>
  opt_defaults_fill: 'blank' | 'missing'
  forced_opt: Record<string, unknown>
  always_enforce_opt: string[]
  set_mock_server_url: boolean
  dynamic_market_type: string | null
  booking_id_in_get_order_path: boolean
}

export interface ApiMutationConfig {
  packages_path: string
  check_in_keys: string[]
  check_out_keys: string[]
  price_keys: string[]
  board_key: string
  room_name_key: string
  currency_key: string
  hotel_id_key: string
  package_id_key: string
  refundable_key: string
  board_values: string[]
  adapter_source_match: string
  booking_id_keys: string[]
  booking_id_fallback_paths: string[]
  booking_id_paths_by_log_type: Record<string, string[]>
  booking_id_format: 'digits' | 'prefix_digits' | 'prefix_hex'
}

export interface ApiSupplierConfig {
  id: string
  env: string
  code: string
  name: string
  supplier_type: 'net' | 'gross'
  supplier_id: string
  auto_id: number
  reference_contract_id: string
  default_supplier_currency: string
  default_contract_currency: string
  log_types: string[]
  package_log_types: string[]
  ui_color: string
  mock_config: ApiMockConfig
  mutation_config: ApiMutationConfig
  field_map: Record<string, unknown> | null
  created_at?: string
  updated_at?: string
}

/** POST/PUT payload — everything on the config except server-owned fields. */
export type SupplierConfigPayload = Omit<
  ApiSupplierConfig,
  'id' | 'env' | 'created_at' | 'updated_at'
>

export interface ApiSupplierListItem {
  code: string
  name: string
  log_types: string[]
  status: string
  env: string
  supplier_type: string
  ui_color: string
  default_supplier_currency: string
  default_contract_currency: string
  ready: boolean
  missing_count: number
}

export interface ApiReadinessCheck {
  key: string
  label: string
  ok: boolean
  detail: string
  blocking: boolean
  fix: string | null
}

export interface ApiSupplierReadiness {
  code: string
  env: string
  ready: boolean
  checks: ApiReadinessCheck[]
}

export interface ApiProbeLogTypeResult {
  log_type: string
  ok: boolean
  error: string | null
  path: string | null
  package_count: number | null
}

export interface ApiProbeResult {
  code: string
  env: string
  ok: boolean
  error: string | null
  plugin: string
  log_types: ApiProbeLogTypeResult[]
}

export interface ApiIngestResult {
  supplier_code: string
  sid: string
  /** Log types written to templates/{CODE}/{LogType}/v1.json. */
  written: string[]
  /** Required log types the SID's logs had nothing usable for. */
  missing: string[]
  /** Rows whose HTTP path couldn't be resolved; dumped to _diagnostics/. */
  unresolved: number
  paths: Record<string, string>
  field_map_paths: number
  sources_seen: string[]
  warning: string | null
}

export interface ApiTemplateUploadResult {
  code: string
  log_type: string
  path: string
  bytes_written: number
}

/** Every call carries X-SMF-Env — supplier config is per environment. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  Object.entries(envHeaders()).forEach(([key, value]) => headers.set(key, value))
  if (init?.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  if (!response.ok) {
    const body = await response.text()
    let detail = body
    try {
      const json = JSON.parse(body) as { detail?: string | { msg?: string }[] }
      if (Array.isArray(json.detail)) {
        // FastAPI validation errors arrive as a list of {loc, msg}.
        detail = json.detail.map((d) => d.msg ?? JSON.stringify(d)).join('; ')
      } else {
        detail = json.detail ?? body
      }
    } catch {
      /* use raw body */
    }
    throw new Error(detail || `HTTP ${response.status}`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function listSupplierItems(): Promise<ApiSupplierListItem[]> {
  return request('/api/suppliers')
}

export function listSupplierConfigs(): Promise<ApiSupplierConfig[]> {
  return request('/api/suppliers/configs')
}

export function getSupplier(code: string): Promise<ApiSupplierConfig> {
  return request(`/api/suppliers/${code}`)
}

export function createSupplier(payload: SupplierConfigPayload): Promise<ApiSupplierConfig> {
  return request('/api/suppliers', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateSupplier(
  code: string,
  payload: SupplierConfigPayload,
): Promise<ApiSupplierConfig> {
  return request(`/api/suppliers/${code}`, { method: 'PUT', body: JSON.stringify(payload) })
}

export function deleteSupplier(code: string): Promise<void> {
  return request(`/api/suppliers/${code}`, { method: 'DELETE' })
}

export function getSupplierReadiness(code: string): Promise<ApiSupplierReadiness> {
  return request(`/api/suppliers/${code}/readiness`)
}

export function uploadSupplierTemplate(
  code: string,
  logType: string,
  expectation: unknown,
): Promise<ApiTemplateUploadResult> {
  return request(`/api/suppliers/${code}/templates/${logType}`, {
    method: 'POST',
    body: JSON.stringify(expectation),
  })
}

/** Build this supplier's templates from a SID's adapter logs. */
export function ingestSupplierFromSid(code: string, sid: string): Promise<ApiIngestResult> {
  return request(`/api/suppliers/${code}/ingest`, {
    method: 'POST',
    body: JSON.stringify({ sid }),
  })
}

export function generateSupplierFieldMap(code: string): Promise<Record<string, unknown>> {
  return request(`/api/suppliers/${code}/field-map/generate`, { method: 'POST' })
}

export function probeSupplier(code: string): Promise<ApiProbeResult> {
  return request(`/api/suppliers/${code}/probe`, { method: 'POST' })
}

export const ALL_LOG_TYPES = [
  'Search',
  'Packages',
  'CancellationPolicy',
  'PreBooking',
  'Booking',
  'GetOrder',
  'CancelOrder',
] as const

/** A blank supplier for the "+ Add supplier" tile. */
export function emptySupplierConfig(): SupplierConfigPayload {
  return {
    code: '',
    name: '',
    supplier_type: 'net',
    supplier_id: '',
    auto_id: 0,
    reference_contract_id: '',
    default_supplier_currency: 'USD',
    default_contract_currency: 'USD',
    log_types: ['Search', 'Packages', 'Booking', 'GetOrder', 'CancelOrder'],
    package_log_types: ['Search', 'Packages'],
    ui_color: '#5c6b6e',
    mock_config: {
      canonical_base: {},
      mock_path_suffix: {},
      opt_field_map: {},
      opt_source: 'ingested',
      path_rewrite: false,
      path_namespaced: false,
      unwrap_adapter_log_body: false,
      opt_defaults: {},
      opt_defaults_fill: 'blank',
      forced_opt: {},
      always_enforce_opt: [],
      set_mock_server_url: true,
      dynamic_market_type: 'DynamicMarkupTarget',
      booking_id_in_get_order_path: false,
    },
    mutation_config: {
      packages_path: '',
      check_in_keys: [],
      check_out_keys: [],
      price_keys: [],
      board_key: '',
      room_name_key: '',
      currency_key: '',
      hotel_id_key: '',
      package_id_key: '',
      refundable_key: '',
      board_values: [],
      adapter_source_match: '',
      booking_id_keys: [],
      booking_id_fallback_paths: [],
      booking_id_paths_by_log_type: {},
      booking_id_format: 'digits',
    },
    field_map: null,
  }
}

/** Strip the server-owned fields so a fetched config can be sent back as a payload. */
export function toPayload(config: ApiSupplierConfig): SupplierConfigPayload {
  return {
    code: config.code,
    name: config.name,
    supplier_type: config.supplier_type,
    supplier_id: config.supplier_id,
    auto_id: config.auto_id,
    reference_contract_id: config.reference_contract_id,
    default_supplier_currency: config.default_supplier_currency,
    default_contract_currency: config.default_contract_currency,
    log_types: config.log_types,
    package_log_types: config.package_log_types,
    ui_color: config.ui_color,
    mock_config: config.mock_config,
    mutation_config: config.mutation_config,
    field_map: config.field_map,
  }
}
