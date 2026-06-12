function resolveApiBase(): string {
  const configured = import.meta.env.VITE_API_URL
  if (configured) return configured
  // Dev: relative URLs → Vite proxy (:5173 → :8000), no CORS preflight.
  if (import.meta.env.DEV) return ''
  return 'http://localhost:8000'
}

export const API_BASE = resolveApiBase()
