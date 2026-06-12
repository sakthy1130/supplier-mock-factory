import { useCallback, useEffect, useState } from 'react'
import { getScenario } from '../api/scenarios'
import type { ScenarioBundle, ScenarioStatus } from '../types/scenario'
import { TERMINAL_STATUSES } from '../types/scenario'

const POLL_MS = 2000

export function useScenarioPoll(scenarioId: string | null) {
  const [bundle, setBundle] = useState<ScenarioBundle | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [polling, setPolling] = useState(false)

  const refresh = useCallback(async () => {
    if (!scenarioId) return null
    const data = await getScenario(scenarioId)
    setBundle(data)
    return data
  }, [scenarioId])

  useEffect(() => {
    if (!scenarioId) {
      setBundle(null)
      setError(null)
      setPolling(false)
      return
    }

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = async () => {
      setPolling(true)
      try {
        const data = await getScenario(scenarioId)
        if (cancelled) return
        setBundle(data)
        setError(null)
        if (!TERMINAL_STATUSES.includes(data.status as ScenarioStatus)) {
          timer = setTimeout(poll, POLL_MS)
        } else {
          setPolling(false)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Poll failed')
          setPolling(false)
        }
      }
    }

    poll()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [scenarioId])

  return { bundle, error, polling, refresh }
}
