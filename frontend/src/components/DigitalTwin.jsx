import { useEffect, useMemo, useState } from 'react'
import { Activity, Check, Layers, Loader2, MapPin, Plus, Save, Trash2 } from 'lucide-react'
import { formatForecastMetrics } from '../forecastMetrics'
import { occupancySparkline, occupancyTrendSummary } from '../occupancyTrend'
import { rankZoneReviewCues } from '../zoneReviewQueue'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function toZoneId(name) {
  return name.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-|-$/g, '').slice(0, 64)
}

function formatVideoTime(seconds) {
  if (!Number.isFinite(seconds)) return '—'
  const minutes = Math.floor(seconds / 60)
  const remainder = Math.floor(seconds % 60)
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

export default function DigitalTwin({ videoId, sourcePreviewUrl, analysisState }) {
  const [zones, setZones] = useState([])
  const [spatial, setSpatial] = useState(null)
  const [zoneForecast, setZoneForecast] = useState(null)
  const [events, setEvents] = useState([])
  const [selectedZoneId, setSelectedZoneId] = useState(null)
  const [zoneName, setZoneName] = useState('')
  const [occupancyCapacity, setOccupancyCapacity] = useState('')
  const [statusThresholds, setStatusThresholds] = useState({ low: '50', moderate: '75', high: '90', critical: '100' })
  const [anomalyMadMultiplier, setAnomalyMadMultiplier] = useState('3')
  const [anomalyMinimumIncrease, setAnomalyMinimumIncrease] = useState('1')
  const [draft, setDraft] = useState([])
  const [isDrawing, setIsDrawing] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState(null)

  const selectedZone = zones.find((zone) => zone.zone_id === selectedZoneId) || zones[0] || null
  const selectedSummary = spatial?.zones?.find((zone) => zone.zone_id === selectedZone?.zone_id)
  const selectedOccupancySamples = (selectedSummary?.occupancy?.timeline || []).flatMap((sample) => (
    Number.isFinite(sample.estimated_mean_visible_people)
      ? [{ elapsed_seconds: sample.bucket_start_seconds, count: sample.estimated_mean_visible_people }]
      : []
  ))
  const zoneReviewCues = rankZoneReviewCues(spatial?.zones)
  const newZoneId = useMemo(() => toZoneId(zoneName), [zoneName])
  const canConfigure = analysisState === 'READY' || analysisState === 'ERROR'

  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      setIsLoading(true)
      setError(null)
      try {
        const zonesResponse = await fetch(`${API_URL}/api/video/${videoId}/zones`, { signal: controller.signal })
        const zonesData = await zonesResponse.json()
        if (!zonesResponse.ok) throw new Error(zonesData.detail || 'Could not load configured zones.')
        setZones(zonesData.zones || [])
        setSelectedZoneId((current) => current || zonesData.zones?.[0]?.zone_id || null)

        if (analysisState === 'COMPLETED') {
          const activeZoneId = selectedZoneId || zonesData.zones?.[0]?.zone_id
          const [spatialResponse, eventsResponse, forecastResponse] = await Promise.all([
            fetch(`${API_URL}/api/video/${videoId}/analysis/spatial`, { signal: controller.signal }),
            fetch(`${API_URL}/api/video/${videoId}/analysis/events?limit=8`, { signal: controller.signal }),
            activeZoneId ? fetch(`${API_URL}/api/video/${videoId}/analysis/zones/${encodeURIComponent(activeZoneId)}/forecast`, { signal: controller.signal }) : Promise.resolve(null),
          ])
          const [spatialData, eventsData, forecastData] = await Promise.all([
            spatialResponse.json(),
            eventsResponse.json(),
            forecastResponse ? forecastResponse.json() : Promise.resolve(null),
          ])
          if (!spatialResponse.ok) throw new Error(spatialData.detail || 'Could not load zone activity.')
          if (!eventsResponse.ok) throw new Error(eventsData.detail || 'Could not load session events.')
          if (forecastResponse && !forecastResponse.ok) throw new Error(forecastData.detail || 'Could not evaluate zone occupancy forecasts.')
          setSpatial(spatialData)
          setEvents(eventsData.events || [])
          setZoneForecast(forecastData)
        } else {
          setSpatial(null)
          setEvents([])
          setZoneForecast(null)
        }
      } catch (loadError) {
        if (loadError.name !== 'AbortError') setError(loadError.message || 'Could not load the zone map.')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [videoId, analysisState, selectedZoneId])

  function handleMapClick(event) {
    if (!isDrawing || !canConfigure) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const x = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width))
    const y = Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height))
    setDraft((current) => [...current, [Number(x.toFixed(4)), Number(y.toFixed(4))]])
  }

  async function saveZones(nextZones) {
    setIsSaving(true)
    setError(null)
    try {
      const response = await fetch(`${API_URL}/api/video/${videoId}/zones`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zones: nextZones }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || 'Could not save the zone map.')
      setZones(data.zones || [])
      setDraft([])
      setIsDrawing(false)
      setSelectedZoneId(data.zones?.at(-1)?.zone_id || data.zones?.[0]?.zone_id || null)
    } catch (saveError) {
      setError(saveError.message || 'Could not save the zone map.')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleSaveZone() {
    if (!zoneName.trim() || !newZoneId || draft.length < 3) return
    if (zones.some((zone) => zone.zone_id === newZoneId)) {
      setError('That zone ID already exists. Choose a different name.')
      return
    }
    const capacity = occupancyCapacity.trim() ? Number(occupancyCapacity) : null
    await saveZones([...zones, {
      zone_id: newZoneId,
      name: zoneName.trim(),
      polygon: draft,
      occupancy_capacity: capacity,
      status_thresholds: Object.fromEntries(Object.entries(statusThresholds).map(([key, value]) => [key, Number(value) / 100])),
      anomaly_mad_multiplier: Number(anomalyMadMultiplier),
      anomaly_minimum_increase: Number(anomalyMinimumIncrease),
    }])
    setZoneName('')
    setOccupancyCapacity('')
  }

  async function handleRemoveZone() {
    if (!selectedZone) return
    await saveZones(zones.filter((zone) => zone.zone_id !== selectedZone.zone_id))
  }

  const maxZoneCount = Math.max(1, ...(spatial?.zones || []).map((zone) => zone.detection_instances))

  return (
    <section aria-label="Digital twin zone map" className="glass-card p-5 sm:p-7 space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-predix-cyan/10 border border-predix-cyan/30 flex items-center justify-center">
            <Layers className="w-5 h-5 text-predix-cyan" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white">Digital Twin · Zone Map</h2>
            <p className="text-xs text-predix-muted">Video-space view with observed activity by configured region</p>
          </div>
        </div>
        <span className="px-2.5 py-1 rounded-md text-[10px] font-mono uppercase tracking-wider border border-predix-border bg-predix-surface text-predix-muted">
          {analysisState === 'COMPLETED' ? 'Session analyzed' : analysisState === 'ANALYZING' ? 'Processing' : 'Ready to configure'}
        </span>
      </div>

      <div className="rounded-lg border border-predix-amber/25 bg-predix-amber/5 px-3 py-2 text-[11px] text-predix-muted">
        This map overlays regions on the uploaded camera view. It is not a physical floor plan or a scale-accurate campus replica.
      </div>

      {error && (
        <div role="alert" className="rounded-lg border border-predix-red/30 bg-predix-red/5 px-3 py-2 text-xs text-predix-red">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-5">
        <div className="xl:col-span-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="label-mono text-[10px] text-predix-muted">Camera frame · normalized coordinates</span>
            {isDrawing && <span className="text-[10px] font-mono text-predix-cyan">Tap frame to add polygon points</span>}
          </div>
          <div className="relative aspect-video overflow-hidden rounded-xl border border-predix-border bg-black">
            {sourcePreviewUrl ? (
              <video src={sourcePreviewUrl} controls preload="metadata" playsInline className="absolute inset-0 w-full h-full object-fill" />
            ) : (
              <div className="absolute inset-0 grid place-items-center text-xs text-predix-muted">Video frame unavailable</div>
            )}
            <svg
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              onClick={handleMapClick}
              className={`absolute inset-0 w-full h-full ${isDrawing ? 'cursor-crosshair' : 'pointer-events-none'}`}
              aria-label="Configured zone polygons"
            >
              {zones.map((zone) => {
                const points = zone.polygon.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')
                const selected = zone.zone_id === selectedZone?.zone_id
                return (
                  <g key={zone.zone_id}>
                    <polygon
                      points={points}
                      fill={selected ? 'rgba(34,211,238,0.22)' : 'rgba(52,211,153,0.14)'}
                      stroke={selected ? '#22d3ee' : '#34d399'}
                      strokeWidth="5"
                      vectorEffect="non-scaling-stroke"
                    />
                    <text x={zone.polygon[0][0] * 1000 + 10} y={zone.polygon[0][1] * 1000 + 30} fill="white" fontSize="30" paintOrder="stroke" stroke="#0b1220" strokeWidth="5">
                      {zone.name}
                    </text>
                  </g>
                )
              })}
              {draft.length > 0 && (
                <>
                  <polyline points={draft.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')} fill="none" stroke="#fbbf24" strokeWidth="5" vectorEffect="non-scaling-stroke" />
                  {draft.map(([x, y], index) => <circle key={`${x}-${y}-${index}`} cx={x * 1000} cy={y * 1000} r="9" fill="#fbbf24" />)}
                </>
              )}
            </svg>
          </div>
          {canConfigure && (
            <div className="rounded-xl border border-predix-border bg-predix-surface/60 p-4 space-y-3">
              <div className="flex flex-col sm:flex-row gap-2">
                <label className="flex-1">
                  <span className="label-mono text-[10px] text-predix-muted block mb-1">New zone name</span>
                  <input
                    value={zoneName}
                    onChange={(event) => setZoneName(event.target.value)}
                    maxLength={100}
                    placeholder="Entrance"
                    className="w-full rounded-lg border border-predix-border bg-predix-bg px-3 py-2 text-sm text-white outline-none focus:border-predix-cyan"
                  />
                </label>
                <div className="sm:w-44">
                  <span className="label-mono text-[10px] text-predix-muted block mb-1">Zone ID</span>
                  <p className="rounded-lg border border-predix-border bg-predix-bg px-3 py-2 text-sm font-mono text-predix-cyan truncate">
                    {newZoneId || '—'}
                  </p>
                </div>
              </div>
              <label className="block max-w-xs">
                <span className="label-mono mb-1 block text-[10px] text-predix-muted">Optional estimated occupancy capacity</span>
                <input type="number" min="1" max="100000" step="1" value={occupancyCapacity} onChange={(event) => setOccupancyCapacity(event.target.value)} placeholder="Leave blank to disable capacity status" className="w-full rounded-lg border border-predix-border bg-predix-bg px-3 py-2 text-sm text-white outline-none focus:border-predix-cyan" />
              </label>
              <div>
                <span className="label-mono mb-2 block text-[10px] text-predix-muted">Status thresholds · percent of configured capacity</span>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {Object.entries(statusThresholds).map(([level, value]) => (
                    <label key={level}>
                      <span className="label-mono mb-1 block text-[8px] uppercase text-predix-muted">{level}</span>
                      <input type="number" min="1" max="100" step="1" value={value} onChange={(event) => setStatusThresholds((current) => ({ ...current, [level]: event.target.value }))} className="w-full rounded-lg border border-predix-border bg-predix-bg px-2 py-2 text-xs text-white outline-none focus:border-predix-cyan" />
                    </label>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label>
                  <span className="label-mono mb-1 block text-[10px] text-predix-muted">Anomaly cutoff · scaled MAD multiplier</span>
                  <input type="number" min="0.1" max="10" step="0.1" value={anomalyMadMultiplier} onChange={(event) => setAnomalyMadMultiplier(event.target.value)} className="w-full rounded-lg border border-predix-border bg-predix-bg px-3 py-2 text-xs text-white outline-none focus:border-predix-cyan" />
                </label>
                <label>
                  <span className="label-mono mb-1 block text-[10px] text-predix-muted">Minimum occupancy rise for a deviation signal</span>
                  <input type="number" min="0" max="100000" step="0.5" value={anomalyMinimumIncrease} onChange={(event) => setAnomalyMinimumIncrease(event.target.value)} className="w-full rounded-lg border border-predix-border bg-predix-bg px-3 py-2 text-xs text-white outline-none focus:border-predix-cyan" />
                </label>
              </div>
              <div className="flex flex-wrap gap-2">
                {!isDrawing ? (
                  <button type="button" onClick={() => { setDraft([]); setIsDrawing(true); setError(null) }} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-predix-cyan px-4 py-2 text-xs font-semibold text-predix-bg">
                    <Plus className="w-4 h-4" /> Draw zone
                  </button>
                ) : (
                  <>
                    <button type="button" disabled={draft.length < 3 || !zoneName.trim() || isSaving} onClick={handleSaveZone} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-predix-cyan px-4 py-2 text-xs font-semibold text-predix-bg disabled:opacity-40">
                      {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />} Save polygon ({draft.length} points)
                    </button>
                    <button type="button" onClick={() => { setDraft([]); setIsDrawing(false) }} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-predix-border px-4 py-2 text-xs text-predix-muted">
                      Cancel
                    </button>
                  </>
                )}
                {selectedZone && !isDrawing && (
                  <button type="button" onClick={handleRemoveZone} disabled={isSaving} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-predix-red/30 px-4 py-2 text-xs text-predix-red disabled:opacity-40">
                    <Trash2 className="w-4 h-4" /> Remove selected
                  </button>
                )}
              </div>
              <p className="text-[10px] text-predix-muted">Use three or more taps to trace a region. Optional capacity statuses compare the estimated sampled-frame occupancy with the configured capacity at each threshold. Detector misses and occlusion can undercount, especially in dense scenes; status is not a verified headcount or safety finding. Thresholds must increase from LOW through CRITICAL. Zones lock when analysis starts.</p>
            </div>
          )}
        </div>

        <div className="xl:col-span-2 space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="label-mono text-[10px] text-predix-muted">Configured zones</span>
              <span className="text-[10px] font-mono text-predix-muted">{zones.length}</span>
            </div>
            {isLoading ? (
              <div className="flex items-center gap-2 py-4 text-xs text-predix-muted"><Loader2 className="w-4 h-4 animate-spin" /> Loading zone map…</div>
            ) : zones.length ? (
              <div className="space-y-2">
                {zones.map((zone) => {
                  const summary = spatial?.zones?.find((item) => item.zone_id === zone.zone_id)
                  const selected = selectedZone?.zone_id === zone.zone_id
                  return (
                    <button key={zone.zone_id} type="button" onClick={() => setSelectedZoneId(zone.zone_id)} className={`w-full rounded-xl border p-3 text-left transition-colors ${selected ? 'border-predix-cyan/50 bg-predix-cyan/5' : 'border-predix-border bg-predix-surface/50'}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 text-sm font-medium text-white"><MapPin className="w-4 h-4 text-predix-cyan" />{zone.name}</span>
                        <span className="font-mono text-xs text-predix-cyan">{summary?.detection_instances ?? '—'}</span>
                      </div>
                      <span className="mt-1 block pl-6 text-[10px] font-mono text-predix-muted">
                        {zone.zone_id} · {summary?.occupancy?.estimation_status === 'estimated'
                          ? `${summary.occupancy.current_estimate} estimated visible people · ${summary.occupancy.status}`
                          : 'track-aware occupancy unavailable'}
                      </span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-predix-border p-4 text-xs text-predix-muted">No zones configured. Draw a polygon over the video frame to begin.</p>
            )}
          </div>

          {analysisState === 'COMPLETED' && spatial && (
            <section aria-label="Rule-based zone review cues" className="rounded-xl border border-predix-amber/25 bg-predix-surface/50 p-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-semibold text-white">Zones with configured review cues</h3>
                <span className="font-mono text-[10px] text-predix-muted">{zoneReviewCues.length}</span>
              </div>
              <p className="mt-1 text-[9px] text-predix-muted">Ordered by configured capacity/deviation rule category for human review. This is not an incident-risk ranking.</p>
              {zoneReviewCues.length ? (
                <ul className="mt-3 space-y-2">
                  {zoneReviewCues.map((zone) => (
                    <li key={zone.zone_id}>
                      <button type="button" onClick={() => setSelectedZoneId(zone.zone_id)} className="w-full rounded-lg border border-predix-border bg-predix-bg/60 p-3 text-left hover:border-predix-amber/50">
                        <span className="flex items-center justify-between gap-2 text-xs font-semibold text-white">
                          {zone.name}
                          <span className="shrink-0 font-mono text-[9px] text-predix-amber">{zone.security_attention.status.replaceAll('_', ' ').toUpperCase()}</span>
                        </span>
                        {zone.security_attention.recommendation && <span className="mt-1 block text-[10px] text-predix-text">{zone.security_attention.recommendation}</span>}
                        {zone.security_attention.signals?.map((signal) => (
                          <span key={signal.signal} className="mt-1 block text-[9px] text-predix-muted">Evidence: {signal.signal.replaceAll('_', ' ')}{signal.status ? ` · ${signal.status}` : ''}{signal.evidence ? ` · ${signal.evidence}` : ''}</span>
                        ))}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-2 text-[10px] text-predix-muted">No configured review cue is available. Missing or absent cues are not a safety determination.</p>
              )}
            </section>
          )}

          {analysisState === 'COMPLETED' && selectedSummary && (
            <div className="rounded-xl border border-predix-border bg-predix-surface/50 p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-white"><Activity className="w-4 h-4 text-predix-cyan" /> {selectedSummary.name} · observed activity</div>
              <div className="grid grid-cols-3 gap-2 rounded-lg border border-predix-border bg-predix-bg/60 p-3">
                <div>
                  <span className="label-mono block text-[8px] text-predix-muted">Current estimate</span>
                  <p className="mt-1 font-mono text-sm text-white">{selectedSummary.occupancy?.estimation_status === 'estimated' ? selectedSummary.occupancy.current_estimate : 'Unavailable'}</p>
                </div>
                <div>
                  <span className="label-mono block text-[8px] text-predix-muted">Peak estimate</span>
                  <p className="mt-1 font-mono text-sm text-white">{selectedSummary.occupancy?.estimation_status === 'estimated' ? selectedSummary.occupancy.peak_estimate : '—'}</p>
                </div>
                <div>
                  <span className="label-mono block text-[8px] text-predix-muted">Observed change</span>
                  <p className="mt-1 font-mono text-sm text-white">{selectedSummary.occupancy?.trend ? `${selectedSummary.occupancy.trend.change > 0 ? '+' : ''}${selectedSummary.occupancy.trend.change}` : '—'}</p>
                </div>
              </div>
              <div className="rounded-lg border border-predix-border bg-predix-bg/60 p-3" aria-label="Observed occupancy trend">
                <span className="label-mono block text-[9px] text-predix-muted">Observed trend · sampled track estimates</span>
                <svg viewBox="0 0 240 42" role="img" aria-label={occupancyTrendSummary(selectedOccupancySamples)} className="mt-2 h-10 w-full rounded bg-predix-surface/60">
                  <polyline points={occupancySparkline(selectedOccupancySamples)} fill="none" stroke="#58e1ee" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
                </svg>
                <p className="mt-1 text-[10px] text-predix-muted">{occupancyTrendSummary(selectedOccupancySamples)} Descriptive only; not a forecast.</p>
              </div>
              <div className="rounded-lg border border-predix-border bg-predix-bg/60 p-3">
                <span className="label-mono block text-[9px] text-predix-muted">Observed track transitions</span>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs text-white">
                  <span>Entries: {selectedSummary.transitions?.status === 'estimated' ? selectedSummary.transitions.observed_entries : 'Unavailable'}</span>
                  <span>Exits: {selectedSummary.transitions?.status === 'estimated' ? selectedSummary.transitions.observed_exits : 'Unavailable'}</span>
                </div>
                {!!selectedSummary.zone_to_zone_transitions?.length && <ul className="mt-2 space-y-1 text-[10px] text-predix-text">
                  {selectedSummary.zone_to_zone_transitions.map((transition) => <li key={`${transition.from_zone_id}-${transition.to_zone_id}`}>Observed movement: {zones.find((zone) => zone.zone_id === transition.from_zone_id)?.name || transition.from_zone_id} → {zones.find((zone) => zone.zone_id === transition.to_zone_id)?.name || transition.to_zone_id} · {transition.observed_count}</li>)}
                </ul>}
                <p className="mt-2 text-[9px] text-predix-muted">Counts require a continuing anonymous track between analyzed samples. Missed detections, track fragmentation, and clip boundaries can omit or misattribute transitions.</p>
              </div>
              <p className="text-[10px] font-mono text-predix-muted">Capacity status: <span className="text-predix-cyan">{selectedSummary.occupancy?.status || 'UNAVAILABLE'}</span>{selectedSummary.occupancy?.capacity_ratio !== null && selectedSummary.occupancy?.capacity_ratio !== undefined ? ` · ${Math.round(selectedSummary.occupancy.capacity_ratio * 100)}% of configured capacity` : ''}</p>
              <div className="rounded-lg border border-predix-border bg-predix-bg/60 p-3">
                <span className="label-mono block text-[9px] text-predix-muted">Occupancy deviation signal</span>
                <p className="mt-1 text-xs font-semibold text-predix-cyan">{selectedSummary.occupancy_anomaly?.status?.replaceAll('_', ' ').toUpperCase() || 'UNAVAILABLE'}</p>
                {selectedSummary.occupancy_anomaly?.latest_signal && <p className="mt-1 text-[10px] text-predix-text">{selectedSummary.occupancy_anomaly.latest_signal.evidence}</p>}
                <p className="mt-1 text-[9px] text-predix-muted">A deviation from recent measured occupancy only. Not an emergency or future-event prediction; this signal has not been evaluated against labeled anomaly events.</p>
              </div>
              <div className="rounded-lg border border-predix-border bg-predix-bg/60 p-3">
                <span className="label-mono block text-[9px] text-predix-muted">Crowd early-warning cue</span>
                <p className="mt-1 text-xs font-semibold text-predix-cyan">{selectedSummary.early_warning?.status?.replaceAll('_', ' ').toUpperCase() || 'INSUFFICIENT DATA'}</p>
                {selectedSummary.early_warning?.signals?.map((signal) => <p key={signal.signal} className="mt-1 text-[10px] text-predix-text">Evidence: {signal.signal.replaceAll('_', ' ')}{signal.status ? ` · ${signal.status}` : ''}</p>)}
                {selectedSummary.early_warning?.recommendation && <p className="mt-1 text-[10px] text-predix-amber">{selectedSummary.early_warning.recommendation}</p>}
                <p className="mt-1 text-[9px] text-predix-muted">This rule combines configured capacity and occupancy-deviation evidence. It is not a validated incident-risk prediction and cannot determine that an emergency will or will not occur.</p>
              </div>
              <div className="rounded-lg border border-predix-border bg-predix-bg/60 p-3">
                <span className="label-mono block text-[9px] text-predix-muted">Security attention review</span>
                <p className="mt-1 text-xs font-semibold text-predix-cyan">{selectedSummary.security_attention?.status?.replaceAll('_', ' ').toUpperCase() || 'UNAVAILABLE'}</p>
                {selectedSummary.security_attention?.recommendation && <p className="mt-1 text-[10px] text-predix-text">{selectedSummary.security_attention.recommendation}</p>}
                {selectedSummary.security_attention?.signals?.map((signal) => <p key={signal.signal} className="mt-1 text-[10px] text-predix-muted">Evidence: {signal.signal.replaceAll('_', ' ')}{signal.status ? ` · ${signal.status}` : ''}{signal.evidence ? ` · ${signal.evidence}` : ''}</p>)}
                <p className="mt-1 text-[9px] text-predix-muted">{selectedSummary.security_attention?.limitation || 'Requires track-aware occupancy and configured capacity. Human review guidance only; it does not assign security resources.'}</p>
              </div>
              <div className="rounded-lg border border-predix-border bg-predix-bg/60 p-3">
                <span className="label-mono block text-[9px] text-predix-muted">Crowd prediction · estimated visible people</span>
                {zoneForecast?.forecasts?.length ? (
                  <div className="mt-2 grid grid-cols-3 gap-2">
                    {zoneForecast.forecasts.map((forecast) => (
                      <div key={forecast.horizon_seconds}>
                        <span className="block text-[9px] font-mono text-predix-muted">{forecast.horizon_seconds / 60} min</span>
                        <p className="mt-1 font-mono text-sm text-white">{forecast.status === 'available' ? `${forecast.forecast} ± ${forecast.uncertainty.mae}` : 'Insufficient data'}</p>
                        {forecast.status === 'available' && <>
                          <span className="block text-[8px] text-predix-muted">{forecast.model}</span>
                          <span className="mt-1 block text-[8px] leading-relaxed text-predix-muted">As of video {formatVideoTime(forecast.as_of_seconds)} · {forecast.supporting_observations} complete 15-second occupancy buckets</span>
                          <span className="mt-1 block text-[8px] leading-relaxed text-predix-muted">{forecast.evaluation?.validation_windows ?? 0} rolling validation windows</span>
                          <span className="mt-1 block text-[8px] leading-relaxed text-predix-muted">{formatForecastMetrics(forecast.evaluation?.selected_model)}</span>
                        </>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-[10px] text-predix-muted">Configure at least one zone to evaluate occupancy forecasts. Predictions require sufficient complete, track-aware observations.</p>
                )}
                <p className="mt-2 text-[9px] text-predix-muted">Rolling-origin MAE; predictions appear only when this session has enough complete observations. Forecasts are estimates, not guarantees.</p>
              </div>
              <div className="space-y-2">
                {selectedSummary.timeline.map((bucket) => {
                  const width = bucket.detection_instances ? Math.max(5, (bucket.detection_instances / maxZoneCount) * 100) : 0
                  return (
                    <div key={`${bucket.bucket_start_seconds}-${bucket.bucket_end_seconds}`}>
                      <div className="mb-1 flex justify-between text-[10px] font-mono text-predix-muted">
                        <span>{formatVideoTime(bucket.bucket_start_seconds)}–{formatVideoTime(bucket.bucket_end_seconds)}</span>
                        <span>{bucket.detection_instances} instances · {bucket.observed_frames} sampled frames{bucket.zone_entries !== null && bucket.zone_entries !== undefined ? ` · +${bucket.zone_entries}/−${bucket.zone_exits} transitions` : ''}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-predix-bg"><div className="h-full rounded-full bg-predix-cyan" style={{ width: `${width}%` }} /></div>
                    </div>
                  )
                })}
              </div>
              <p className="text-[10px] text-predix-muted">Zone estimates use detected anonymous person tracks whose box centers fall inside each polygon. Detector misses, occlusion, track fragmentation, and merges can cause undercounts or overcounts. Capacity status compares this unvalidated estimate with the operator-configured threshold; it is not a verified headcount or safety finding. Legacy sessions and zones without valid polygons show occupancy as unavailable. Forecasts require sufficient rolling validation and are not guarantees.</p>
            </div>
          )}

          {analysisState === 'COMPLETED' && (
            <div className="rounded-xl border border-predix-border bg-predix-surface/50 p-4">
              <div className="mb-2 flex items-center justify-between text-xs font-semibold text-white"><span>Session events</span><Check className="w-4 h-4 text-predix-emerald" /></div>
              {events.length ? (
                <ul className="space-y-2">
                  {events.map((event) => (
                    <li key={event.event_id} className="flex items-start justify-between gap-3 border-t border-predix-border/60 pt-2 text-[11px]">
                      <span className="text-predix-text">{event.count} {event.object_class}{event.count === 1 ? '' : ' instances'} · {event.zone_name || 'outside configured zones'}</span>
                      <span className="shrink-0 font-mono text-predix-muted">{formatVideoTime(event.timestamp_seconds)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[11px] text-predix-muted">No object events were generated from the observed frames.</p>
              )}
            </div>
          )}

          <p className="text-[10px] text-predix-muted">Historical comparisons are unavailable until sessions are stored in the historical data layer.</p>
        </div>
      </div>
    </section>
  )
}
