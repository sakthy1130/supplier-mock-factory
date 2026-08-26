function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_URL
  if (configured) return configured
  // Dev: relative URLs → Vite proxy (:5144 → :8001), no CORS preflight.
  if (import.meta.env.DEV) return ''
  return 'http://localhost:8001'
}

export const API_BASE = resolveApiBase()

// ── Active environment (dev | stg) ──────────────────────────────────────────
// A live toggle, not a rebuild: every request carries X-SMF-Env so the backend
// resolves the matching Settings + supplier registry + Quickwit index for that
// env. Persisted in localStorage so a page refresh keeps the last selection.

export type SmfEnv = 'dev' | 'stg' | 'odis'

export const SMF_ENVS: readonly SmfEnv[] = ['dev', 'stg', 'odis']

export const SMF_ENV_LABELS: Record<SmfEnv, string> = {
  dev: 'Dev',
  stg: 'Staging',
  odis: 'ODIS Staging',
}

const ENV_STORAGE_KEY = 'smf-active-env'

function readInitialEnv(): SmfEnv {
  if (typeof window === 'undefined') return 'dev'
  // Membership test rather than a stg/dev ternary — with three envs the old
  // binary check silently rewrote anything that wasn't 'stg' back to 'dev'.
  const stored = window.localStorage.getItem(ENV_STORAGE_KEY) as SmfEnv | null
  return stored && SMF_ENVS.includes(stored) ? stored : 'dev'
}

let activeEnv: SmfEnv = readInitialEnv()

export function getActiveEnv(): SmfEnv {
  return activeEnv
}

export function setActiveEnv(env: SmfEnv): void {
  activeEnv = env
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(ENV_STORAGE_KEY, env)
  }
}

/** Header every API request must carry so the backend targets the right env. */
export function envHeaders(): Record<string, string> {
  return { 'X-SMF-Env': activeEnv }
}

/** FastAPI answers a validation failure with `detail` as an ARRAY of error objects,
 *  not a string. Passing that straight to `new Error()` rendered "[object Object]" and
 *  threw away a perfectly good message. Pull out msg (dropping pydantic's "Value error,"
 *  prefix) and say which field it came from. */
export function formatApiError(body: string, status: number): string {
  try {
    const json = JSON.parse(body) as { detail?: unknown }
    const detail = json.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const messages = detail.map((entry) => {
        const item = entry as { msg?: string; loc?: (string | number)[] }
        const msg = (item.msg ?? '').replace(/^Value error,\s*/, '')
        // Skip the "body" prefix and array indices — "suppliers.packages" reads better
        // than "body.suppliers.0.packages".
        const field = (item.loc ?? [])
          .filter((part) => part !== 'body' && typeof part !== 'number')
          .join('.')
        return field && msg ? `${field}: ${msg}` : msg || field
      })
      const unique = [...new Set(messages.filter(Boolean))]
      if (unique.length) return unique.join(' · ')
    }
  } catch {
    /* fall through to the raw body */
  }
  return body || `HTTP ${status}`
}

