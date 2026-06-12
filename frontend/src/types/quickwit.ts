export interface QuickwitHit {
  [key: string]: unknown
}

export interface QuickwitSearchResponse {
  index: string
  query: string
  minutes: number
  status: number
  num_hits: number
  hits: QuickwitHit[]
}
