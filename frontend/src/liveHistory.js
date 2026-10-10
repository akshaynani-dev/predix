export function buildLiveZoneHistoryUrl(apiUrl, sessionId, zoneId) {
  if (!sessionId || !zoneId) throw new Error('A live session and zone are required.')
  const url = new URL(apiUrl)
  const basePath = url.pathname.replace(/\/$/, '')
  url.pathname = `${basePath}/api/live/sessions/${encodeURIComponent(sessionId)}/zones/${encodeURIComponent(zoneId)}/occupancy`
  return url.toString()
}

export async function fetchLiveZoneHistory({ apiUrl, sessionId, zoneId, signal, fetchImpl = fetch }) {
  const response = await fetchImpl(buildLiveZoneHistoryUrl(apiUrl, sessionId, zoneId), { signal })
  if (!response.ok) throw new Error(`Live zone history request failed (${response.status}).`)
  return response.json()
}

export function buildLiveAlertHistoryUrl(apiUrl, sessionId) {
  if (!sessionId) throw new Error('A live session is required.')
  const url = new URL(apiUrl)
  const basePath = url.pathname.replace(/\/$/, '')
  url.pathname = `${basePath}/api/live/sessions/${encodeURIComponent(sessionId)}/alerts`
  url.searchParams.set('limit', '100')
  return url.toString()
}

export async function fetchLiveAlertHistory({ apiUrl, sessionId, signal, fetchImpl = fetch }) {
  const response = await fetchImpl(buildLiveAlertHistoryUrl(apiUrl, sessionId), { signal })
  if (!response.ok) throw new Error(`Live alert history request failed (${response.status}).`)
  return response.json()
}
