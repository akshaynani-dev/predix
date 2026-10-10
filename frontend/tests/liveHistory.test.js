import test from 'node:test'
import assert from 'node:assert/strict'
import { buildLiveAlertHistoryUrl, buildLiveZoneHistoryUrl, fetchLiveAlertHistory, fetchLiveZoneHistory } from '../src/liveHistory.js'

test('builds live zone history paths under a configured API base path', () => {
  assert.equal(
    buildLiveZoneHistoryUrl('https://predix.example/prefix', 'session id', 'zone/entry'),
    'https://predix.example/prefix/api/live/sessions/session%20id/zones/zone%2Fentry/occupancy',
  )
})

test('fetches the history response and forwards abort signals', async () => {
  const controller = new AbortController()
  let received
  const payload = { observations: [], predictions: [] }
  const result = await fetchLiveZoneHistory({
    apiUrl: 'http://localhost:8000', sessionId: 'session', zoneId: 'entry',
    signal: controller.signal,
    fetchImpl: async (url, options) => {
      received = { url, options }
      return { ok: true, json: async () => payload }
    },
  })
  assert.deepEqual(result, payload)
  assert.equal(received.options.signal, controller.signal)
  assert.match(received.url, /\/zones\/entry\/occupancy$/)
})

test('reports unavailable history responses instead of rendering fabricated data', async () => {
  await assert.rejects(fetchLiveZoneHistory({
    apiUrl: 'http://localhost:8000', sessionId: 'session', zoneId: 'entry',
    fetchImpl: async () => ({ ok: false, status: 503 }),
}), /503/)
})

test('builds the live alert episode history URL with an encoded session ID', () => {
  assert.equal(
    buildLiveAlertHistoryUrl('https://predix.example/base/', 'session id'),
    'https://predix.example/base/api/live/sessions/session%20id/alerts?limit=100',
  )
})

test('fetches persisted alert episodes and forwards cancellation', async () => {
  const controller = new AbortController()
  let options
  const payload = { alerts: [{ status: 'resolved' }] }
  const response = await fetchLiveAlertHistory({
    apiUrl: 'http://localhost:8000', sessionId: 'session', signal: controller.signal,
    fetchImpl: async (_url, receivedOptions) => {
      options = receivedOptions
      return { ok: true, json: async () => payload }
    },
  })
  assert.deepEqual(response, payload)
  assert.equal(options.signal, controller.signal)
})
