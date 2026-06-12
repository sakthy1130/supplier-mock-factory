import { PROGRESS_STATUSES, type ScenarioStatus } from '../types/scenario'

const LABELS: Record<ScenarioStatus, string> = {
  PENDING: 'Queued',
  BUILDING_MOCKS: 'Build mocks',
  REGISTERING: 'Register',
  CREATING_CONTRACTS: 'Contracts',
  CREATING_API_KEY: 'ApiKey',
  READY: 'Ready',
  FAILED: 'Failed',
  TORN_DOWN: 'Torn down',
}

interface Props {
  status: ScenarioStatus
  polling: boolean
}

export function ScenarioProgress({ status, polling }: Props) {
  const activeIndex = PROGRESS_STATUSES.indexOf(status)
  const failed = status === 'FAILED'

  return (
    <div className="pipeline">
      <div className="pipeline-header">
        <h3>Provisioning pipeline</h3>
        {polling && status !== 'READY' && status !== 'FAILED' && <span className="pulse-dot" title="Polling" />}
      </div>
      <div className="pipeline-steps">
        {PROGRESS_STATUSES.map((step, index) => {
          const done = !failed && activeIndex > index
          const active = status === step || (status === 'READY' && step === 'READY')
          const failedHere = failed && index === Math.max(activeIndex, 0)
          const classes = [
            'pipeline-step',
            done ? 'done' : '',
            active ? 'active' : '',
            failedHere ? 'failed' : '',
          ]
            .filter(Boolean)
            .join(' ')

          return (
            <div key={step} className={classes}>
              <div className="step-circle">{done ? '✓' : index + 1}</div>
              <div className="step-label">{LABELS[step]}</div>
            </div>
          )
        })}
      </div>
      {polling && status !== 'READY' && status !== 'FAILED' && (
        <p className="hint" style={{ marginTop: '0.85rem' }}>
          Checking status every 2 seconds…
        </p>
      )}
    </div>
  )
}
