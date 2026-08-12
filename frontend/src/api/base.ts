function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_URL
  if (configured) return configured
  // Dev: relative URLs → Vite proxy (:5173 → :8000), no CORS preflight.
  if (import.meta.env.DEV) return ''
  return 'http://localhost:8000'
}

export const API_BASE = resolveApiBase()

// ── Active environment (dev | stg) ──────────────────────────────────────────
// A live toggle, not a rebuild: every request carries X-SMF-Env so the backend
// resolves the matching Settings + supplier registry + Quickwit index for that
// env. Persisted in localStorage so a page refresh keeps the last selection.

export type SmfEnv = 'dev' | 'stg'

const ENV_STORAGE_KEY = 'smf-active-env'

function readInitialEnv(): SmfEnv {
  if (typeof window === 'undefined') return 'dev'
  return window.localStorage.getItem(ENV_STORAGE_KEY) === 'stg' ? 'stg' : 'dev'
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
