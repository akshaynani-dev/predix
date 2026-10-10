export const ANALYSIS_POLL_INTERVAL_MS = 1500
export const MAX_STATUS_POLL_FAILURES = 5

export function statusPollRetryDelay(failureCount) {
  const safeFailureCount = Math.max(1, Math.floor(failureCount))
  return Math.min(ANALYSIS_POLL_INTERVAL_MS * (2 ** (safeFailureCount - 1)), 15000)
}
