import { useEffect, useState } from 'react'
import { Activity, BarChart3, Clock3, Loader2, MapPin, Video } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function formatTime(seconds) {
  if (!Number.isFinite(seconds)) return '—'
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.floor(seconds % 60)
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

function Metric({ label, value, detail, icon: Icon }) {
  return (
    <div className="glass-card p-4 sm:p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="label-mono text-[10px] text-predix-muted">{label}</span>
        <Icon className="h-4 w-4 text-predix-cyan" />
      </div>
      <p className="font-mono text-2xl font-bold text-white">{value}</p>
      <p className="mt-1 text-[10px] text-predix-muted">{detail}</p>
    </div>
  )
}

export default function AnalyticsDashboard({ videoId, analysisResult, videoMetadata }) {
  const [temporal, setTemporal] = useState(null)
  const [spatial, setSpatial] = useState(null)
  const [historySessions, setHistorySessions] = useState([])
  const [patterns, setPatterns] = useState(null)
  const [prediction, setPrediction] = useState(null)
  const [decisionSupport, setDecisionSupport] = useState(null)
  const [selectedHistory, setSelectedHistory] = useState(null)
  const [historyRange, setHistoryRange] = useState(null)
  const [historyStart, setHistoryStart] = useState('')
  const [historyEnd, setHistoryEnd] = useState('')
  const [historyLoadingId, setHistoryLoadingId] = useState(null)
  const [historyError, setHistoryError] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    async function loadAnalytics() {
      setIsLoading(true)
      setError(null)
      try {
        const [temporalResponse, spatialResponse, historyResponse, patternResponse, predictionResponse, decisionResponse] = await Promise.all([
          fetch(`${API_URL}/api/video/${videoId}/analysis/temporal?bucket_seconds=15`, { signal: controller.signal }),
          fetch(`${API_URL}/api/video/${videoId}/analysis/spatial?bucket_seconds=15`, { signal: controller.signal }),
          fetch(`${API_URL}/api/history/sessions?limit=20`, { signal: controller.signal }),
          fetch(`${API_URL}/api/history/patterns`, { signal: controller.signal }),
          fetch(`${API_URL}/api/history/predictions/activity-rate`, { signal: controller.signal }),
          fetch(`${API_URL}/api/history/decision-support`, { signal: controller.signal }),
        ])
        const [temporalData, spatialData, historyData, patternData, predictionData, decisionData] = await Promise.all([
          temporalResponse.json(),
          spatialResponse.json(),
          historyResponse.json(),
          patternResponse.json(),
          predictionResponse.json(),
          decisionResponse.json(),
        ])
        if (!temporalResponse.ok) throw new Error(temporalData.detail || 'Temporal analytics are unavailable.')
        if (!spatialResponse.ok) throw new Error(spatialData.detail || 'Spatial analytics are unavailable.')
        if (!historyResponse.ok) throw new Error(historyData.detail || 'Historical sessions are unavailable.')
        if (!patternResponse.ok) throw new Error(patternData.detail || 'Historical pattern analysis is unavailable.')
        if (!predictionResponse.ok) throw new Error(predictionData.detail || 'Prediction evaluation is unavailable.')
        if (!decisionResponse.ok) throw new Error(decisionData.detail || 'Decision support is unavailable.')
        setTemporal(temporalData)
        setSpatial(spatialData)
        setHistorySessions((historyData.sessions || []).filter((session) => session.status === 'completed' && session.video_id !== videoId))
        setPatterns(patternData)
        setPrediction(predictionData)
        setDecisionSupport(decisionData)
      } catch (loadError) {
        if (loadError.name !== 'AbortError') setError(loadError.message || 'Analytics could not be loaded.')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    loadAnalytics()
    return () => controller.abort()
  }, [videoId])

  async function inspectHistoricalSession(sessionId) {
    setHistoryLoadingId(sessionId)
    setHistoryError(null)
    setHistoryRange(null)
    try {
      const response = await fetch(`${API_URL}/api/history/sessions/${sessionId}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not open historical session.')
      setSelectedHistory(data.session)
    } catch (loadError) {
      setHistoryError(loadError.message || 'Could not open historical session.')
    } finally {
      setHistoryLoadingId(null)
    }
  }

  async function queryHistoricalRange(event) {
    event.preventDefault()
    if (!selectedHistory) return
    const parameters = new URLSearchParams()
    if (historyStart !== '') parameters.set('start_seconds', historyStart)
    if (historyEnd !== '') parameters.set('end_seconds', historyEnd)
    setHistoryError(null)
    try {
      const response = await fetch(`${API_URL}/api/history/sessions/${selectedHistory.video_id}/activity?${parameters}`)
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not query the selected time range.')
      setHistoryRange(data)
    } catch (loadError) {
      setHistoryError(loadError.message || 'Could not query the selected time range.')
    }
  }

  const buckets = temporal?.aggregation?.timeline || []
  const maxInstances = Math.max(1, ...buckets.map((bucket) => bucket.detection_instances))
  const stats = temporal?.aggregation?.statistics
  const activeZones = spatial?.active_zones ?? 0
  const metadata = videoMetadata || {}

  return (
    <section aria-label="Video analytics dashboard" className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-2">
        <div>
          <p className="label-mono text-[10px] uppercase tracking-widest text-predix-cyan">Observed session analytics</p>
          <h2 className="mt-1 text-xl font-semibold text-white">Activity overview</h2>
        </div>
        <span className="w-fit rounded-md border border-predix-emerald/30 bg-predix-emerald/5 px-2.5 py-1 text-[10px] font-mono uppercase text-predix-emerald">
          Analysis completed
        </span>
      </div>

      {error && <div role="alert" className="rounded-lg border border-predix-red/30 bg-predix-red/5 px-4 py-3 text-xs text-predix-red">{error}</div>}

      {isLoading ? (
        <div className="glass-card flex items-center gap-2 p-6 text-sm text-predix-muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading analytics from stored observations…</div>
      ) : !error && temporal && spatial && (
        <>
          <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
            <Metric label="Detection instances" value={analysisResult.total_detection_instances.toLocaleString()} detail="Frame-level model observations" icon={Activity} />
            <Metric label="Active zones" value={activeZones} detail={`${spatial.configured_zones} configured zones`} icon={MapPin} />
            <Metric label="Structured events" value={(analysisResult.total_events || 0).toLocaleString()} detail="Derived from sampled detections" icon={BarChart3} />
            <Metric label="Processing" value={`${analysisResult.processing_fps} fps`} detail={`${analysisResult.processing_time_seconds}s elapsed · ${analysisResult.device_name}`} icon={Clock3} />
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <article className="glass-card p-5 xl:col-span-2">
              <div className="mb-4 flex items-center justify-between gap-2">
                <div>
                  <h3 className="text-sm font-semibold text-white">Activity over video time</h3>
                  <p className="mt-1 text-[10px] text-predix-muted">Observed detection instances per 15-second bucket</p>
                </div>
                <Activity className="h-4 w-4 text-predix-cyan" />
              </div>
              {buckets.length ? (
                <>
                  <div className="flex h-36 items-end gap-1 border-b border-l border-predix-border px-2 pb-1">
                    {buckets.map((bucket) => {
                      const height = bucket.detection_instances ? Math.max(3, bucket.detection_instances / maxInstances * 100) : 0
                      return (
                        <div
                          key={bucket.bucket_start_seconds}
                          title={`${formatTime(bucket.bucket_start_seconds)}–${formatTime(bucket.bucket_end_seconds)} · ${bucket.detection_instances} instances across ${bucket.observed_frames} sampled frames`}
                          aria-label={`${bucket.detection_instances} detections from ${formatTime(bucket.bucket_start_seconds)} to ${formatTime(bucket.bucket_end_seconds)}`}
                          className="min-w-1 flex-1 rounded-t-sm bg-predix-cyan/80 hover:bg-predix-cyan"
                          style={{ height: `${height}%` }}
                        />
                      )
                    })}
                  </div>
                  <div className="mt-2 flex justify-between text-[10px] font-mono text-predix-muted">
                    <span>{formatTime(buckets[0].bucket_start_seconds)}</span>
                    <span>{formatTime(buckets[buckets.length - 1].bucket_end_seconds)}</span>
                  </div>
                </>
              ) : (
                <p className="rounded-lg border border-dashed border-predix-border p-4 text-xs text-predix-muted">No sampled frame observations are available for this timeline.</p>
              )}
              <p className="mt-3 text-[10px] text-predix-muted">Each sample is an observed frame. Repeated appearances may refer to the same object; PREDIX does not track identities.</p>
            </article>

            <article className="glass-card p-5">
              <div className="mb-4 flex items-center justify-between">
                <div><h3 className="text-sm font-semibold text-white">Activity periods</h3><p className="mt-1 text-[10px] text-predix-muted">Derived across observed buckets</p></div>
                <Clock3 className="h-4 w-4 text-predix-cyan" />
              </div>
              {stats?.peak_period ? (
                <div className="space-y-3">
                  <div className="rounded-lg border border-predix-cyan/20 bg-predix-cyan/5 p-3">
                    <span className="label-mono text-[9px] text-predix-muted">Peak observed period</span>
                    <p className="mt-1 font-mono text-sm text-white">{formatTime(stats.peak_period.bucket_start_seconds)}–{formatTime(stats.peak_period.bucket_end_seconds)}</p>
                    <span className="text-[10px] text-predix-muted">{stats.peak_period.average_instances_per_observed_frame} avg instances / sample</span>
                  </div>
                  <div className="rounded-lg border border-predix-border bg-predix-surface/60 p-3">
                    <span className="label-mono text-[9px] text-predix-muted">Quietest observed period</span>
                    <p className="mt-1 font-mono text-sm text-white">{formatTime(stats.quiet_period.bucket_start_seconds)}–{formatTime(stats.quiet_period.bucket_end_seconds)}</p>
                    <span className="text-[10px] text-predix-muted">{stats.quiet_period.average_instances_per_observed_frame} avg instances / sample</span>
                  </div>
                  <p className="text-[10px] text-predix-muted">Overall mean: {stats.mean_instances_per_observed_frame} instances per sampled frame.</p>
                </div>
              ) : <p className="text-xs text-predix-muted">Insufficient observations for period statistics.</p>}
            </article>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <article className="glass-card p-5">
              <h3 className="mb-1 text-sm font-semibold text-white">Detected categories</h3>
              <p className="mb-4 text-[10px] text-predix-muted">Counts from actual sampled model outputs</p>
              {Object.keys(temporal.counts_by_class || {}).length ? (
                <div className="space-y-2">
                  {Object.entries(temporal.counts_by_class).sort((a, b) => b[1] - a[1]).map(([name, count]) => (
                    <div key={name} className="flex items-center justify-between border-b border-predix-border/60 pb-2 text-xs">
                      <span className="capitalize text-predix-text">{name}</span><span className="font-mono text-white">{count.toLocaleString()}</span>
                    </div>
                  ))}
                </div>
              ) : <p className="text-xs text-predix-muted">No object instances were detected in the sampled frames.</p>}
            </article>

            <article className="glass-card p-5">
              <h3 className="mb-1 text-sm font-semibold text-white">Confidence distribution</h3>
              <p className="mb-4 text-[10px] text-predix-muted">Confidence values from stored detections</p>
              <div className="space-y-3">
                {(temporal.confidence_distribution || []).map((bin) => {
                  const width = bin.count ? Math.max(4, bin.count / Math.max(1, temporal.total_detection_instances) * 100) : 0
                  return (
                    <div key={bin.range}>
                      <div className="mb-1 flex justify-between text-[10px] font-mono text-predix-muted"><span>{bin.range}</span><span>{bin.count}</span></div>
                      <div className="h-2 rounded-full bg-predix-bg"><div className="h-full rounded-full bg-predix-emerald" style={{ width: `${width}%` }} /></div>
                    </div>
                  )
                })}
              </div>
            </article>

            <article className="glass-card p-5">
              <div className="mb-3 flex items-center gap-2"><Video className="h-4 w-4 text-predix-cyan" /><h3 className="text-sm font-semibold text-white">Video source</h3></div>
              <dl className="space-y-3 text-xs">
                <div className="flex justify-between gap-2"><dt className="text-predix-muted">Duration</dt><dd className="font-mono text-white">{metadata.duration_seconds != null ? `${metadata.duration_seconds}s` : '—'}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-predix-muted">Resolution</dt><dd className="font-mono text-white">{metadata.width && metadata.height ? `${metadata.width} × ${metadata.height}` : '—'}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-predix-muted">Frame rate</dt><dd className="font-mono text-white">{metadata.fps != null ? `${metadata.fps} FPS` : '—'}</dd></div>
                <div className="flex justify-between gap-2"><dt className="text-predix-muted">Frames analyzed</dt><dd className="font-mono text-white">{analysisResult.inference_frames.toLocaleString()} / {analysisResult.frames_processed.toLocaleString()}</dd></div>
              </dl>
            </article>
          </div>

          {!spatial.configured_zones && (
            <p className="rounded-lg border border-predix-border bg-predix-surface/50 px-4 py-3 text-xs text-predix-muted">No zones were configured for this session. Zone comparisons are unavailable.</p>
          )}
          <article className="glass-card p-5">
            <div className="mb-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-white">Historical sessions</h3>
                <p className="mt-1 text-[10px] text-predix-muted">Completed sessions stored in the local history database</p>
              </div>
              <span className="label-mono text-[10px] text-predix-muted">{historySessions.length} earlier sessions</span>
            </div>
            {historyError && <p role="alert" className="mb-3 text-xs text-predix-red">{historyError}</p>}
            {historySessions.length ? (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="space-y-2">
                  {historySessions.map((session) => (
                    <button
                      key={session.video_id}
                      type="button"
                      onClick={() => inspectHistoricalSession(session.video_id)}
                      className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${selectedHistory?.video_id === session.video_id ? 'border-predix-cyan/50 bg-predix-cyan/5' : 'border-predix-border bg-predix-surface/40'}`}
                    >
                      <span className="block truncate text-xs font-medium text-white">{session.filename}</span>
                      <span className="mt-1 flex flex-wrap justify-between gap-2 text-[10px] font-mono text-predix-muted">
                        <span>{new Date(session.created_at).toLocaleString()}</span>
                        <span>{session.total_detection_instances ?? 0} instances · {session.total_events ?? 0} events</span>
                      </span>
                    </button>
                  ))}
                </div>
                {selectedHistory && (
                  <div className="rounded-xl border border-predix-border bg-predix-surface/40 p-4">
                    {historyLoadingId ? (
                      <div className="flex items-center gap-2 text-xs text-predix-muted"><Loader2 className="h-4 w-4 animate-spin" /> Loading historical session…</div>
                    ) : (
                      <>
                        <h4 className="truncate text-xs font-semibold text-white">{selectedHistory.filename}</h4>
                        <p className="mt-1 text-[10px] text-predix-muted">{new Date(selectedHistory.created_at).toLocaleString()} · {selectedHistory.summary?.model || 'Model unavailable'}</p>
                        <div className="mt-3 grid grid-cols-2 gap-2 text-[10px]">
                          <div className="rounded-lg bg-predix-bg/70 p-2"><span className="block text-predix-muted">Observed instances</span><span className="font-mono text-white">{selectedHistory.summary?.total_detection_instances ?? '—'}</span></div>
                          <div className="rounded-lg bg-predix-bg/70 p-2"><span className="block text-predix-muted">Events</span><span className="font-mono text-white">{selectedHistory.summary?.total_events ?? '—'}</span></div>
                        </div>
                        <form onSubmit={queryHistoricalRange} className="mt-4 space-y-2">
                          <p className="label-mono text-[9px] text-predix-muted">Query video-time range (seconds)</p>
                          <div className="grid grid-cols-2 gap-2">
                            <label className="text-[9px] text-predix-muted">Start
                              <input type="number" min="0" step="1" value={historyStart} onChange={(event) => setHistoryStart(event.target.value)} className="mt-1 w-full rounded-md border border-predix-border bg-predix-bg px-2 py-2 text-xs text-white" placeholder="0" />
                            </label>
                            <label className="text-[9px] text-predix-muted">End
                              <input type="number" min="0" step="1" value={historyEnd} onChange={(event) => setHistoryEnd(event.target.value)} className="mt-1 w-full rounded-md border border-predix-border bg-predix-bg px-2 py-2 text-xs text-white" placeholder="Full session" />
                            </label>
                          </div>
                          <button type="submit" className="min-h-10 w-full rounded-lg border border-predix-cyan/30 bg-predix-cyan/5 px-3 py-2 text-xs text-predix-cyan">Query stored measurements</button>
                        </form>
                        {historyRange && (
                          <div className="mt-3 rounded-lg border border-predix-border p-3 text-[10px]">
                            <span className="text-predix-muted">{historyRange.measurements.length} stored buckets</span>
                            <span className="ml-2 font-mono text-white">{historyRange.statistics.mean_instances_per_observed_frame ?? '—'} mean instances / frame</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-predix-border p-4 text-xs text-predix-muted">No earlier completed sessions are available yet. Completed analyses will appear here for comparison.</p>
            )}
          </article>
          <article className="glass-card p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-white">Recurring observations</h3>
                <p className="mt-1 text-[10px] text-predix-muted">Pattern discovery from stored sessions · no forecasts</p>
              </div>
              <span className="label-mono text-[10px] text-predix-muted">{patterns?.session_count ?? 0} sessions</span>
            </div>
            {patterns?.patterns?.length ? (
              <ul className="space-y-2">
                {patterns.patterns.map((pattern, index) => (
                  <li key={`${pattern.pattern_type}-${pattern.zone_id || pattern.object_class || index}`} className="rounded-lg border border-predix-border bg-predix-surface/40 p-3">
                    <p className="text-xs text-predix-text">{pattern.description}</p>
                    <p className="mt-1 text-[10px] font-mono text-predix-muted">Evidence: {pattern.supporting_sessions} of {pattern.session_count} sessions</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-lg border border-dashed border-predix-border p-4 text-xs text-predix-muted">
                {patterns?.message || 'Insufficient historical data for reliable pattern analysis.'}
              </p>
            )}
            <p className="mt-3 text-[10px] text-predix-muted">Patterns describe repeated observations only. They do not predict future activity.</p>
          </article>
          <article className="glass-card p-5">
            <div className="mb-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-white">Predictive intelligence</h3>
                <p className="mt-1 text-[10px] text-predix-muted">Next-session activity rate · evaluated on earlier sessions</p>
              </div>
              <span className="label-mono text-[10px] text-predix-muted">{prediction?.observed_sessions ?? 0} compatible sessions</span>
            </div>
            {prediction?.status === 'available' ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="rounded-lg border border-predix-cyan/25 bg-predix-cyan/5 p-3">
                  <span className="label-mono text-[9px] text-predix-muted">Predicted activity rate</span>
                  <p className="mt-1 font-mono text-xl font-bold text-predix-cyan">{prediction.prediction.expected_value}</p>
                  <span className="text-[10px] text-predix-muted">instances per sampled frame</span>
                </div>
                <div className="rounded-lg border border-predix-border bg-predix-surface/50 p-3">
                  <span className="label-mono text-[9px] text-predix-muted">Estimated range</span>
                  <p className="mt-1 font-mono text-sm text-white">{prediction.prediction.uncertainty.estimated_range.minimum}–{prediction.prediction.uncertainty.estimated_range.maximum}</p>
                  <span className="text-[10px] text-predix-muted">± rolling-origin MAE; not a probability interval</span>
                </div>
                <div className="rounded-lg border border-predix-border bg-predix-surface/50 p-3">
                  <span className="label-mono text-[9px] text-predix-muted">Time-ordered evaluation</span>
                  <p className="mt-1 font-mono text-sm text-white">MAE {prediction.evaluation.mae} · RMSE {prediction.evaluation.rmse}</p>
                  <span className="text-[10px] text-predix-muted">{prediction.evaluation.test_windows} rolling-origin test windows</span>
                </div>
                <p className="md:col-span-3 text-[10px] text-predix-muted">{prediction.prediction.model} · predicts the next compatible uploaded session. This is an estimate, not a guaranteed outcome.</p>
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-predix-border p-4 text-xs text-predix-muted">
                {prediction?.message || 'Insufficient data for reliable prediction.'}
              </p>
            )}
            <div className="mt-4 rounded-lg border border-predix-border bg-predix-surface/40 p-3">
              <h4 className="text-xs font-semibold text-white">Decision support</h4>
              {decisionSupport?.recommendations?.length ? (
                decisionSupport.recommendations.map((item) => (
                  <div key={item.type} className="mt-2">
                    <p className="text-xs text-predix-cyan">{item.message}</p>
                    <p className="mt-1 text-[10px] text-predix-muted">Predicted {item.basis.predicted_value} vs. historical 75th percentile {item.basis.historical_75th_percentile} across {item.basis.historical_session_count} compatible sessions.</p>
                  </div>
                ))
              ) : (
                <p className="mt-1 text-[10px] text-predix-muted">{decisionSupport?.message || 'No recommendation is available.'}</p>
              )}
              {decisionSupport?.status === 'available' && <p className="mt-2 text-[10px] text-predix-muted">Review suggestions alongside local context; this is decision support, not an operational directive.</p>}
            </div>
          </article>
        </>
      )}
    </section>
  )
}
