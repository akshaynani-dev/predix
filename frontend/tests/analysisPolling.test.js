import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ANALYSIS_POLL_INTERVAL_MS,
  MAX_STATUS_POLL_FAILURES,
  statusPollRetryDelay,
} from '../src/analysisPolling.js'

test('analysis status failures use bounded exponential backoff', () => {
  assert.equal(MAX_STATUS_POLL_FAILURES, 5)
  assert.deepEqual(
    Array.from({ length: MAX_STATUS_POLL_FAILURES }, (_, index) => statusPollRetryDelay(index + 1)),
    [1500, 3000, 6000, 12000, 15000],
  )
  assert.equal(statusPollRetryDelay(0), ANALYSIS_POLL_INTERVAL_MS)
  assert.equal(statusPollRetryDelay(20), 15000)
})
