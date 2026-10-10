import assert from 'node:assert/strict'
import test from 'node:test'
import { occupancySparkline, occupancyTrendSummary } from '../src/occupancyTrend.js'

test('does not draw a trend before two real samples exist', () => {
  assert.equal(occupancySparkline([]), '')
  assert.equal(occupancyTrendSummary([]), 'Collecting occupancy samples.')
})

test('uses sampled estimates and elapsed time to draw an occupancy trace', () => {
  const samples = [
    { elapsed_seconds: 2, count: 1 },
    { elapsed_seconds: 8, count: 3 },
    { elapsed_seconds: 20, count: 2 },
  ]
  assert.equal(occupancySparkline(samples), '3.0,39.0 81.0,3.0 237.0,21.0')
  assert.equal(occupancyTrendSummary(samples), 'Increased by 1 estimates across 3 recent samples over 18s (+3.3 estimates/min observed).')
})

test('constant estimates are shown as stable without fabricated changes', () => {
  const samples = [
    { elapsed_seconds: 1, count: 4 },
    { elapsed_seconds: 2, count: 4 },
  ]
  assert.equal(occupancyTrendSummary(samples), 'No net change across 2 recent samples over 1s.')
  assert.equal(occupancySparkline(samples), '3.0,21.0 237.0,21.0')
})

test('ignores invalid occupancy samples and avoids a rate without elapsed time', () => {
  const samples = [
    { elapsed_seconds: 4, count: 2 },
    { elapsed_seconds: Number.NaN, count: 500 },
    { elapsed_seconds: 4, count: 3 },
    { elapsed_seconds: 5, count: -1 },
  ]
  assert.equal(occupancyTrendSummary(samples), 'Increased by 1 estimates across 2 recent samples over an unknown time span.')
})
