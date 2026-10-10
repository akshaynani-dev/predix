export function occupancySparkline(samples, width = 240, height = 42, padding = 3) {
  const valid = samples.filter((sample) => (
    Number.isFinite(sample.elapsed_seconds)
    && Number.isFinite(sample.count)
    && sample.count >= 0
  ))
  if (valid.length < 2) return ''

  const firstTime = valid[0].elapsed_seconds
  const lastTime = valid.at(-1).elapsed_seconds
  const duration = lastTime - firstTime
  const counts = valid.map((sample) => sample.count)
  const minimum = Math.min(...counts)
  const maximum = Math.max(...counts)
  const rawRange = maximum - minimum
  const valueRange = rawRange || 1

  return valid.map((sample, index) => {
    const xFraction = duration > 0 ? (sample.elapsed_seconds - firstTime) / duration : index / (valid.length - 1)
    const yFraction = rawRange ? (sample.count - minimum) / valueRange : 0.5
    const x = padding + xFraction * (width - padding * 2)
    const y = height - padding - yFraction * (height - padding * 2)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

export function occupancyTrendSummary(samples) {
  const valid = samples.filter((sample) => (
    Number.isFinite(sample.elapsed_seconds)
    && Number.isFinite(sample.count)
    && sample.count >= 0
  ))
  if (valid.length < 2) return 'Collecting occupancy samples.'
  const change = valid.at(-1).count - valid[0].count
  const duration = valid.at(-1).elapsed_seconds - valid[0].elapsed_seconds
  const sampleWindow = `${valid.length} recent samples over ${formatDuration(duration)}`
  if (change === 0) return `No net change across ${sampleWindow}.`
  const changePerMinute = duration > 0 ? (change * 60) / duration : null
  const direction = change > 0 ? 'Increased' : 'Decreased'
  const rate = changePerMinute === null
    ? ''
    : ` (${changePerMinute > 0 ? '+' : ''}${changePerMinute.toFixed(1)} estimates/min observed)`
  return `${direction} by ${Math.abs(change)} estimates across ${sampleWindow}${rate}.`
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return 'an unknown time span'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = seconds / 60
  return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} min`
}
