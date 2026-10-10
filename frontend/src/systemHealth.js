export function systemHealthLabel(requestStatus, response) {
  if (requestStatus === 'loading' || requestStatus === 'idle') return 'CHECKING'
  if (requestStatus === 'error') return 'OFFLINE'
  if (response?.status === 'online') return 'OPERATIONAL'
  return 'DEGRADED'
}
