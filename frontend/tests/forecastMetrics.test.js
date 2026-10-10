import assert from 'node:assert/strict'
import test from 'node:test'
import { formatForecastMetrics } from '../src/forecastMetrics.js'

test('forecast metric summary includes errors, fit, and MAPE denominator', () => {
  assert.equal(
    formatForecastMetrics({
      mae: 1.25,
      rmse: 1.5,
      r_squared: 0.8,
      mape_percent: 12.5,
      mape_samples: 4,
      mape_zero_actuals_excluded: 2,
    }),
    'MAE 1.25 · RMSE 1.5 · R² 0.8 · MAPE 12.5% (4 nonzero actuals; 2 zero actuals excluded)',
  )
})

test('undefined metrics are labeled and never rendered as zero', () => {
  assert.equal(
    formatForecastMetrics({ mae: 0, rmse: 0, r_squared: null, mape_percent: null, mape_samples: 0, mape_zero_actuals_excluded: 3 }),
    'MAE 0 · RMSE 0 · R² not defined · MAPE not defined (0 nonzero actuals; 3 zero actuals excluded)',
  )
  assert.equal(formatForecastMetrics(null), 'Validation metrics unavailable')
})
