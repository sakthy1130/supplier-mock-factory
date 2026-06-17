export type SupplierCode = 'HBS' | 'EXP' | 'RHK'

export type ScenarioStatus =
  | 'PENDING'
  | 'BUILDING_MOCKS'
  | 'REGISTERING'
  | 'CREATING_CONTRACTS'
  | 'CREATING_API_KEY'
  | 'READY'
  | 'FAILED'
  | 'TORN_DOWN'

export interface PackageSpec {
  count: number
  room_basis: string
  prices: number[]
  refundable: boolean[]
}

export interface SupplierScenario {
  code: SupplierCode
  packages: PackageSpec
}

export interface ScenarioRequest {
  namespace: string
  check_in: string
  check_out: string
  atg_hotel_id: string
  suppliers: SupplierScenario[]
}

export interface ScenarioBundle {
  id?: string
  namespace: string
  status: ScenarioStatus
  api_key?: string
  api_key_id?: string
  contracts: Record<string, string>
  booking_ids: Record<string, string>
  check_in: string
  check_out: string
  atg_hotel_id: string
  supplier_hotel_ids?: Record<string, string>
  crawla_export?: Record<string, unknown> | null
  br_setup?: Record<string, unknown> | null
  mock_server_base_url?: string
  expectation_count: number
  error_message?: string
  created_at?: string
  expires_at?: string
  provisioning_log?: string[]
}

export interface ScenarioListItem {
  id: string
  namespace: string
  status: ScenarioStatus
  created_at?: string
  suppliers: string[]
}

export const TERMINAL_STATUSES: ScenarioStatus[] = ['READY', 'FAILED', 'TORN_DOWN']

export const PROGRESS_STATUSES: ScenarioStatus[] = [
  'PENDING',
  'BUILDING_MOCKS',
  'REGISTERING',
  'CREATING_CONTRACTS',
  'CREATING_API_KEY',
  'READY',
]
