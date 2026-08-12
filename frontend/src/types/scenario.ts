export type SupplierCode = 'HBS' | 'EXP' | 'RHK' | 'CHC' | 'EXT'

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
  // 0-based index of the package the Booking/GetOrder flow is built for.
  // null/undefined means no booking flow (only search + package mocks).
  booking_package_index?: number | null
}

export const DEFAULT_ROOM_NAME = '1 Double Bed, Nonsmoking'
export const DEFAULT_ROOM_BASIS = 'RO'

export const DEFAULT_SUPPLIER_CURRENCIES: Record<SupplierCode, string> = {
  HBS: 'EUR',
  EXP: 'USD',
  RHK: 'USD',
  CHC: 'SAR',
  EXT: 'EUR',
}

export type AssignmentTarget = 'apikey' | 'sbgroup' | 'both'

export interface SupplierScenario {
  code: SupplierCode
  contract_currency: string
  packages: PackageSpec
  // Where this supplier's contract attaches when SmartBooking is on. Default apikey.
  assignment_target?: AssignmentTarget
}

export interface ScenarioRequest {
  namespace: string
  check_in: string
  check_out: string
  atg_hotel_id: string
  supplier_hotel_ids?: Record<string, string>
  suppliers: SupplierScenario[]
  assign_to_br?: boolean
  // Create the apiKey with SmartBooking enabled (backend fills default SB config).
  sb_enabled?: boolean
  template_id?: string
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
