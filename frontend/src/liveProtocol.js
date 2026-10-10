export const MAX_RECONNECTS = 3

function boundedInteger(value, fallback, minimum, maximum) {
  if (value === undefined || value === null || value === '') return fallback
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(maximum, Math.max(minimum, Math.round(parsed)))
}

export function getLiveCaptureSettings({ frameWidth, frameHeight, frameIntervalMs } = {}) {
  return {
    frameWidth: boundedInteger(frameWidth, 640, 320, 1280),
    frameHeight: boundedInteger(frameHeight, 720, 240, 720),
    frameIntervalMs: boundedInteger(frameIntervalMs, 500, 250, 10000),
  }
}

export function buildRtspStartMessage(value) {
  try {
    const url = new URL(value.trim())
    if (!['rtsp:', 'rtsps:'].includes(url.protocol) || !url.hostname || url.hash) return null
    return JSON.stringify({ type: 'start_rtsp', url: url.toString() })
  } catch {
    return null
  }
}

export function buildHlsSourceUrl(value) {
  try {
    const url = new URL(value.trim())
    if (
      url.protocol !== 'https:'
      || !url.hostname
      || url.username
      || url.password
      || url.hash
      || !url.pathname.toLowerCase().endsWith('.m3u8')
    ) return null
    return url.toString()
  } catch {
    return null
  }
}

export function reconnectDelay(attempt) {
  return Math.min(500 * (2 ** attempt), 4000)
}

export function liveStatusLabel(status) {
  return {
    idle: 'OFFLINE',
    connecting: 'CONNECTING',
    live: 'LIVE',
    reconnecting: 'RECONNECTING',
    offline: 'STREAM DISCONNECTED',
    error: 'ERROR',
    source_error: 'SOURCE ERROR',
  }[status] || 'OFFLINE'
}
