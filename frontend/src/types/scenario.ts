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

export type PreBookingStatus = 'available' | 'price_changed' | 'sold_out'

/** Expedia's own wire values, so the field and the mock body say the same thing. */
export const PREBOOKING_STATUSES: { value: PreBookingStatus; label: string }[] = [
  { value: 'available', label: 'Available (default)' },
  { value: 'price_changed', label: 'Price changed' },
  { value: 'sold_out', label: 'Sold out (stops before booking)' },
]

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
  /**
   * Which price-check response this supplier's PreBooking mock returns. Omit for
   * 'available' (today's behaviour). 'sold_out' also skips Booking/GetOrder/CancelOrder
   * — that body carries no book link, so the chain genuinely stops at PreBooking.
   */
  prebooking_status?: PreBookingStatus
  /** Only with 'price_changed': the re-quoted price, in supplier currency. */
  prebooking_changed_price?: number | null
  /**
   * EXP explicit pricing, per package, both or neither: the split of `prices` into
   * pre-markup + markup, in supplier currency, where price = original_price_with_vat +
   * markup. The price becomes the mock's totals.inclusive and `markup` its
   * totals.marketing_fee, which is what the EXP adapter reports as markup.dynamic. Omit to
   * keep the price-only flow.
   */
  original_price_with_vat?: number[]
  markup?: number[]
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

export const DEFAULT_SUPPLIER_CURRENCIES: Record<SupplierCode, string> = {
  HBS: 'EUR',
  EXP: 'USD',
  RHK: 'USD',
  CHC: 'SAR',
  EXT: 'EUR',
}

export type AssignmentTarget = 'apikey' | 'sbgroup' | 'both'

/** How far provisioning goes past the mocks and contracts. 'full' is the historical
 *  behaviour and stays the default. */
export type ProvisioningDepth = 'contract_only' | 'contract_br' | 'full'

export const PROVISIONING_DEPTHS: { value: ProvisioningDepth; label: string; hint: string }[] = [
  {
    value: 'contract_only',
    label: 'Mocks + contract only',
    hint: 'No apiKey is created. Optionally attach the contract to an apiKey you already have.',
  },
  {
    value: 'contract_br',
    label: 'Mocks + contract, contract → BR',
    hint:
      'Also assigns the contract to the Static/Dynamic Markup rules. No apiKey is created — ' +
      'an existing one given below is assigned to those two rules as well.',
  },
  {
    value: 'full',
    label: 'Mocks + contract + apiKey',
    hint: 'Creates a new apiKey and attaches the contracts to it. Required for SmartBooking.',
  },
]

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
  provisioning_depth?: ProvisioningDepth
  // Attach the contracts to this existing apiKey instead of creating one.
  // Only meaningful for the contract_only / contract_br depths.
  existing_api_key?: string | null
  /**
   * BR markup output values for the Static (rule 3) and Dynamic (rule 4) Markup rules.
   * Sent as typed — the backend normalizes `10` → `10%` and `10-15` → `10%-15%`. Omit for
   * the defaults (10% and 15%-25%). Only the depths that provision BR accept them.
   */
  static_markup?: string
  dynamic_markup?: string
}

export interface ScenarioBundle {
  id?: string
  namespace: string
  env: string
  status: ScenarioStatus
  api_key?: string
  api_key_id?: string
  // api_key refers to a PRE-EXISTING apiKey this scenario only attached contracts to;
  // teardown detaches rather than deleting it.
  api_key_is_external?: boolean
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
