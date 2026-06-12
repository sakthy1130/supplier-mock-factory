import { API_BASE } from './base'

export interface HotelMappingResponse {
  atg_hotel_id: string
  supplier_hotel_ids: Record<string, string>
}

export async function resolveHotelMapping(atgHotelId: string, suppliers: string[]) {
  const params = new URLSearchParams({
    atg_hotel_id: atgHotelId,
    suppliers: suppliers.join(','),
  })
  const response = await fetch(`${API_BASE}/api/hotels/mapping?${params}`)
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
  return response.json() as Promise<HotelMappingResponse>
}
