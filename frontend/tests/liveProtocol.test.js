import assert from 'node:assert/strict'
import test from 'node:test'
import { buildHlsSourceUrl, buildRtspStartMessage, getLiveCaptureSettings, liveStatusLabel, MAX_RECONNECTS, reconnectDelay } from '../src/liveProtocol.js'

test('live capture settings default safely and clamp to supported bounds', () => {
  assert.deepEqual(getLiveCaptureSettings(), { frameWidth: 640, frameHeight: 720, frameIntervalMs: 500 })
  assert.deepEqual(getLiveCaptureSettings({ frameWidth: '960', frameHeight: '540', frameIntervalMs: '750' }), {
    frameWidth: 960,
    frameHeight: 540,
    frameIntervalMs: 750,
  })
  assert.deepEqual(getLiveCaptureSettings({ frameWidth: 2000, frameHeight: 1080, frameIntervalMs: 0 }), {
    frameWidth: 1280,
    frameHeight: 720,
    frameIntervalMs: 250,
  })
  assert.deepEqual(getLiveCaptureSettings({ frameWidth: 'invalid', frameHeight: 'invalid', frameIntervalMs: 'invalid' }), {
    frameWidth: 640,
    frameHeight: 720,
    frameIntervalMs: 500,
  })
})

test('reconnect policy is bounded and backs off between attempts', () => {
  assert.equal(MAX_RECONNECTS, 3)
  assert.deepEqual(
    Array.from({ length: MAX_RECONNECTS }, (_, attempt) => reconnectDelay(attempt)),
    [500, 1000, 2000],
  )
  assert.equal(reconnectDelay(10), 4000)
})

test('live states have operator-facing status labels', () => {
  assert.equal(liveStatusLabel('live'), 'LIVE')
  assert.equal(liveStatusLabel('reconnecting'), 'RECONNECTING')
  assert.equal(liveStatusLabel('offline'), 'STREAM DISCONNECTED')
  assert.equal(liveStatusLabel('unknown'), 'OFFLINE')
})

test('RTSP handshake accepts RTSP protocols and rejects unsupported or malformed URLs', () => {
  assert.deepEqual(JSON.parse(buildRtspStartMessage('rtsp://camera.example/live')), {
    type: 'start_rtsp',
    url: 'rtsp://camera.example/live',
  })
  assert.equal(buildRtspStartMessage('https://camera.example/live'), null)
  assert.equal(buildRtspStartMessage('rtsp:///missing-host'), null)
  assert.equal(buildRtspStartMessage('not a url'), null)
})

test('native HLS source accepts HTTPS playlists and rejects unsafe or unsupported URLs', () => {
  assert.equal(buildHlsSourceUrl('https://camera.example/live/index.m3u8?token=abc'), 'https://camera.example/live/index.m3u8?token=abc')
  for (const url of [
    'http://camera.example/live.m3u8',
    'https://user:pass@camera.example/live.m3u8',
    'https://camera.example/live.mp4',
    'https://camera.example/live.m3u8#fragment',
    'not a URL',
  ]) assert.equal(buildHlsSourceUrl(url), null)
})
