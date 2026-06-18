export type TestStatus = 'PASSED' | 'FAILED' | 'SKIPPED' | 'ABORTED'
export type RunStatus = 'RUNNING' | 'COMPLETE' | 'ABORTED'

export interface HttpDetails {
  method: string
  url: string
  request_body: string | null
  response_status: number
  response_body: string | null
}

export interface StepNode {
  name: string
  status: string | null
  duration_ms: number
  steps?: StepNode[]
}

export interface TestResult {
  scenario_id: string | null
  test_class: string
  test_method: string
  status: TestStatus
  duration_ms: number
  steps?: StepNode[]
  failure_message: string | null
  stack_trace: string | null
  failed_step: string | null
  http_details: HttpDetails | null
  posted_at: string
  provisioning_log?: string[]
}

export interface TestRunState {
  run_id: string
  status: RunStatus
  total: number
  passed: number
  failed: number
  skipped: number
  results: TestResult[]
  started_at: string
  completed_at: string | null
}
