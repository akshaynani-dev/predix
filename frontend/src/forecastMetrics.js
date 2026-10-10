export function formatForecastMetrics(metrics) {
  if (!metrics) return 'Validation metrics unavailable'

  const rSquared = metrics.r_squared == null ? 'not defined' : metrics.r_squared
  const mape = metrics.mape_percent == null ? 'not defined' : `${metrics.mape_percent}%`
  const mapeSamples = Number.isInteger(metrics.mape_samples)
    ? ` (${metrics.mape_samples} nonzero actuals; ${metrics.mape_zero_actuals_excluded ?? 0} zero actuals excluded)`
    : ''

  return `MAE ${metrics.mae ?? '—'} · RMSE ${metrics.rmse ?? '—'} · R² ${rSquared} · MAPE ${mape}${mapeSamples}`
}
