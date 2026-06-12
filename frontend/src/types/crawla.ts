export type CrawlaBucket =
  | 'CRAWLA_LOWER'
  | 'EXPEDIA_LOWER'
  | 'EQUAL'
  | 'ONLY_EXPEDIA'
  | 'ONLY_CRAWLA'

export interface CrawlaAnchorRequest {
  check_in: string
  check_out: string
  atg_hotel_ids: string[]
}

export interface CrawlaSearchAnchorItem {
  atg_id: string
  min_price?: number | null
  total_amount?: number | null
  room_name?: string | null
  room_basis?: string | null
  base_amount?: number | null
  tax_amount?: number | null
  currency?: string | null
}

export interface CrawlaHotelOffer {
  room_id: string
  room_name: string
  total_amount: number
  room_basis?: string | null
  meal?: string | null
  refundability?: string | null
  bed_type?: string | null
}

export interface CrawlaHotelAnchorItem {
  atg_id: string
  min_price?: number | null
  status?: string | null
  data: CrawlaHotelOffer[]
}

export interface CrawlaAnchorSearchResponse {
  data: CrawlaSearchAnchorItem[]
}

export interface CrawlaAnchorPackagesResponse {
  hotels: CrawlaHotelAnchorItem[]
}

export interface CrawlaPricePanel {
  crawla_total: number
  exp_mode: 'INCLUDE_HOTEL' | 'EXCLUDE_HOTEL'
  exp_price: number
  hbs_price: number
}

export type CrawlaPackagePriceMode = 'SAME' | 'INCREASE' | 'DECREASE'

export interface CrawlaPackagesPanel extends CrawlaPricePanel {
  package_count: number
  package_price_mode: CrawlaPackagePriceMode
  package_price_step: number
  crawla_room_id: string
  crawla_room_name: string
  room_basis: string
  meal?: string
  refundability: string
  bed_type?: string | null
}

export interface CrawlaScenarioRequest {
  namespace: string
  check_in: string
  check_out: string
  atg_hotel_id: string
  bucket: CrawlaBucket
  search: CrawlaPricePanel
  packages: CrawlaPackagesPanel
}

export interface CrawlaScenarioRunResult {
  scenario_id: string
  search_s_id: string
  search_status: string
  search_hotel_id: string
  package_p_id: string
  package_status: string
  error_message?: string | null
  logs: Array<{
    step: string
    method: string
    path: string
    attempt: string
    status: string
    http_status: string
  }>
}
