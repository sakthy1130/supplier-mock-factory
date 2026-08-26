import type { ApiTemplatePackageRow } from '../api/scenarioTemplates'

function pick(row: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (row[key] !== undefined) return row[key]
  }
  return undefined
}

function toBool(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'string') return ['true', 'yes', '1'].includes(value.trim().toLowerCase())
  return Boolean(value)
}

/** A numeric cell that may be absent — undefined when the key is missing or blank. */
function optionalAmount(
  row: Record<string, unknown>,
  keys: string[],
  index: number,
  label: string,
): number | undefined {
  const raw = pick(row, keys)
  if (raw === undefined || raw === null || (typeof raw === 'string' && !raw.trim())) {
    return undefined
  }
  const value = typeof raw === 'string' ? Number(raw.trim()) : raw
  if (typeof value !== 'number' || Number.isNaN(value)) {
    throw new Error(`Row ${index + 1}: ${label} must be a number`)
  }
  return value
}

/**
 * Accepts a pasted JSON array of package rows in whatever casing the source
 * table used (roomName/room_name/RoomName, Refundability/refundable, ...) and
 * normalizes it to the API shape. Throws a descriptive Error per bad row
 * instead of silently dropping or misreading data.
 */
export function parseTemplatePackagesJson(raw: string): ApiTemplatePackageRow[] {
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch (err) {
    throw new Error(`Invalid JSON: ${err instanceof Error ? err.message : 'could not parse'}`)
  }
  if (!Array.isArray(data) || data.length === 0) {
    throw new Error('Expected a JSON array with at least one package row')
  }

  return data.map((entry, index) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new Error(`Row ${index + 1}: expected an object`)
    }
    const row = entry as Record<string, unknown>
    const roomName = pick(row, ['roomName', 'room_name', 'RoomName', 'Room Name'])
    const price = pick(row, ['price', 'Price'])
    const roomBasis = pick(row, ['roomBasis', 'room_basis', 'RoomBasis', 'Room Basis']) ?? 'RO'
    const refundable = pick(row, ['refundable', 'Refundable', 'refundability', 'Refundability']) ?? true

    if (typeof roomName !== 'string' || !roomName.trim()) {
      throw new Error(`Row ${index + 1}: missing roomName`)
    }
    const priceNum = typeof price === 'string' ? Number(price) : price
    if (typeof priceNum !== 'number' || Number.isNaN(priceNum)) {
      throw new Error(`Row ${index + 1}: price must be a number`)
    }

    // EXP explicit pricing, optional and all-or-nothing per row. Absent keys stay absent
    // rather than becoming 0, which the backend would read as a real price.
    const originalPriceWithVat = optionalAmount(
      row,
      ['originalPriceWithVat', 'original_price_with_vat', 'originalPriceWithVAT', 'Original Price With VAT'],
      index,
      'originalPriceWithVat',
    )
    const markup = optionalAmount(row, ['markup', 'Markup'], index, 'markup')

    return {
      room_name: roomName.trim(),
      room_basis: String(roomBasis).trim().toUpperCase() || 'RO',
      price: priceNum,
      refundable: toBool(refundable),
      ...(originalPriceWithVat !== undefined ? { original_price_with_vat: originalPriceWithVat } : {}),
      ...(markup !== undefined ? { markup } : {}),
    }
  })
}
