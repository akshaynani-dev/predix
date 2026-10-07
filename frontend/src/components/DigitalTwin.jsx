import { useEffect, useMemo, useState } from 'react'
import { Activity, Check, Layers, Loader2, MapPin, Plus, Save, Trash2 } from 'lucide-react'

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
  const [events, setEvents] = useState([])
  const [selectedZoneId, setSelectedZoneId] = useState(null)
  const [zoneName, setZoneName] = useState('')
  const [draft, setDraft] = useState([])
  const [isDrawing, setIsDrawing] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState(null)

  const selectedZone = zones.find((zone) => zone.zone_id === selectedZoneId) || zones[0] || null
  const selectedSummary = spatial?.zones?.find((zone) => zone.zone_id === selectedZone?.zone_id)
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
          const [spatialResponse, eventsResponse] = await Promise.all([
            fetch(`${API_URL}/api/video/${videoId}/analysis/spatial`, { signal: controller.signal }),
            fetch(`${API_URL}/api/video/${videoId}/analysis/events?limit=8`, { signal: controller.signal }),
          ])
          const [spatialData, eventsData] = await Promise.all([
            spatialResponse.json(),
            eventsResponse.json(),
          ])
          if (!spatialResponse.ok) throw new Error(spatialData.detail || 'Could not load zone activity.')
          if (!eventsResponse.ok) throw new Error(eventsData.detail || 'Could not load session events.')
          setSpatial(spatialData)
          setEvents(eventsData.events || [])
        } else {
          setSpatial(null)
          setEvents([])
        }
      } catch (loadError) {
        if (loadError.name !== 'AbortError') setError(loadError.message || 'Could not load the zone map.')
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    }
    load()
    return () => controller.abort()
  }, [videoId, analysisState])

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
    await saveZones([...zones, { zone_id: newZoneId, name: zoneName.trim(), polygon: draft }])
    setZoneName('')
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
              <p className="text-[10px] text-predix-muted">Use three or more taps to trace a region. Zones use normalized video coordinates and become locked when analysis starts.</p>
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
                      <span className="mt-1 block pl-6 text-[10px] font-mono text-predix-muted">{zone.zone_id} · observed instances</span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-predix-border p-4 text-xs text-predix-muted">No zones configured. Draw a polygon over the video frame to begin.</p>
            )}
          </div>

          {analysisState === 'COMPLETED' && selectedSummary && (
            <div className="rounded-xl border border-predix-border bg-predix-surface/50 p-4 space-y-3">
              <div className="flex items-center gap-2 text-xs font-semibold text-white"><Activity className="w-4 h-4 text-predix-cyan" /> {selectedSummary.name} · observed activity</div>
              <div className="space-y-2">
                {selectedSummary.timeline.map((bucket) => {
                  const width = bucket.detection_instances ? Math.max(5, (bucket.detection_instances / maxZoneCount) * 100) : 0
                  return (
                    <div key={`${bucket.bucket_start_seconds}-${bucket.bucket_end_seconds}`}>
                      <div className="mb-1 flex justify-between text-[10px] font-mono text-predix-muted">
                        <span>{formatVideoTime(bucket.bucket_start_seconds)}–{formatVideoTime(bucket.bucket_end_seconds)}</span>
                        <span>{bucket.detection_instances} instances · {bucket.observed_frames} sampled frames</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-predix-bg"><div className="h-full rounded-full bg-predix-cyan" style={{ width: `${width}%` }} /></div>
                    </div>
                  )
                })}
              </div>
              <p className="text-[10px] text-predix-muted">Counts come from sampled detector frames. They do not represent unique tracked people or a physical occupancy sensor.</p>
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
