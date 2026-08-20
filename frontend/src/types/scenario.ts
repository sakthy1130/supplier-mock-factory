/** A supplier code. Open by design — suppliers are configured on the Suppliers
 *  screen, so the UI can never know the full set at build time. */
export type SupplierCode = string

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
  room_basis: string[]
  room_names: string[]
  supplier_currency: string
  prices: number[]
  refundable: boolean[]
  /**
   * Occupancy the mocked rates advertise. Derby BTS (CHC, HIL) drops every rate whose
   * occupancy differs from the searched one — silently, with zero results. Omit to take
   * the backend default of 2 adults, which is what the default search uses.
   */
  adults?: number
  child_ages?: number[]
  room_count?: number
}

export const DEFAULT_ROOM_NAME = '1 Double Bed, Nonsmoking'
export const DEFAULT_ROOM_BASIS = 'RO'

export interface SupplierScenario {
  code: SupplierCode
  contract_currency: string
  packages: PackageSpec
}

export interface ScenarioRequest {
  namespace: string
  check_in: string
  check_out: string
  atg_hotel_id: string
  supplier_hotel_ids?: Record<string, string>
  suppliers: SupplierScenario[]
  assign_to_br?: boolean
}

export interface ScenarioBundle {
  id?: string
  namespace: string
  env: string
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
  env: string
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
