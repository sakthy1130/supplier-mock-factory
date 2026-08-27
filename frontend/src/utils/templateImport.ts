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

/** One supplier lifted out of a scenario request, in the import form's shape. */
export interface ScenarioImportSupplier {
  supplier: string
  supplier_currency: string
  contract_currency: string
  assignment_target: 'apikey' | 'sbgroup' | 'both'
  rows: ApiTemplatePackageRow[]
  prebooking_status: 'available' | 'price_changed' | 'sold_out'
  prebooking_changed_price?: number
  booking_package_index?: number
}

export interface ScenarioImport {
  atg_hotel_id: string
  sb_enabled: boolean
  suppliers: ScenarioImportSupplier[]
}

/** True when this JSON is a scenario request/bundle rather than a package-row array.
 *  Lets one paste box accept either without the user picking a mode. */
export function looksLikeScenarioJson(raw: string): boolean {
  try {
    const data = JSON.parse(raw) as Record<string, unknown>
    if (Array.isArray(data) || typeof data !== 'object' || data === null) return false
    const candidate = (data.request as Record<string, unknown>) ?? data
    return Array.isArray(candidate?.suppliers)
  } catch {
    return false
  }
}

/**
 * Turn a scenario request — or a whole scenario bundle, whose `request` holds one —
 * into the import form's fields.
 *
 * The two shapes are inverses: a scenario stores packages as parallel ARRAYS
 * (prices[i], room_names[i]) while a template stores a list of ROWS. Pasting a
 * scenario into the row-array box used to fail with "Expected a JSON array", which is
 * technically true and completely unhelpful — this is the missing half.
 */
export function parseScenarioJson(raw: string): ScenarioImport {
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(raw) as Record<string, unknown>
  } catch (err) {
    throw new Error(`Invalid JSON: ${err instanceof Error ? err.message : 'could not parse'}`)
  }
  // Accept the scenario detail response as-is, not just its `request` node.
  const req = ((parsed.request as Record<string, unknown>) ?? parsed) as Record<string, unknown>
  const suppliersIn = req.suppliers
  if (!Array.isArray(suppliersIn) || suppliersIn.length === 0) {
    throw new Error('That JSON has no "suppliers" — paste a scenario request or a package-row array')
  }

  const at = (value: unknown, index: number, fallback: unknown): unknown =>
    Array.isArray(value) && index < value.length ? value[index] : fallback

  const suppliers = suppliersIn.map((entry, sIndex) => {
    const block = entry as Record<string, unknown>
    const packages = (block.packages ?? {}) as Record<string, unknown>
    const prices = (packages.prices as unknown[]) ?? []
    const count = (packages.count as number) ?? prices.length
    if (!count) {
      throw new Error(`Supplier ${sIndex + 1}: no packages to import`)
    }
    const split = (packages.original_price_with_vat as number[]) ?? []
    const markup = (packages.markup as number[]) ?? []
    const hasSplit = split.length === count && markup.length === count

    const rows: ApiTemplatePackageRow[] = Array.from({ length: count }, (_, i) => ({
      room_name: String(at(packages.room_names, i, 'Room')),
      room_basis: String(at(packages.room_basis, i, 'RO')),
      price: Number(at(prices, i, 0)),
      refundable: Boolean(at(packages.refundable, i, true)),
      ...(hasSplit
        ? { original_price_with_vat: Number(split[i]), markup: Number(markup[i]) }
        : {}),
    }))

    return {
      supplier: String(block.code ?? ''),
      supplier_currency: String(packages.supplier_currency ?? 'SAR').toUpperCase().slice(0, 3),
      contract_currency: String(block.contract_currency ?? 'USD').toUpperCase().slice(0, 3),
      assignment_target: (block.assignment_target as ScenarioImportSupplier['assignment_target']) ?? 'apikey',
      rows,
      prebooking_status:
        (packages.prebooking_status as ScenarioImportSupplier['prebooking_status']) ?? 'available',
      ...(packages.prebooking_changed_price != null
        ? { prebooking_changed_price: Number(packages.prebooking_changed_price) }
        : {}),
      ...(packages.booking_package_index != null
        ? { booking_package_index: Number(packages.booking_package_index) }
        : {}),
    }
  })

  return {
    atg_hotel_id: String(req.atg_hotel_id ?? ''),
    sb_enabled: Boolean(req.sb_enabled),
    suppliers,
  }
}
