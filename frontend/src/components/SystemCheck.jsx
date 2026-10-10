import { useEffect, useState } from 'react'
import { Radio, Loader, ChevronRight } from 'lucide-react'
import { systemHealthLabel } from '../systemHealth'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function SystemCheck() {
  const [status, setStatus]       = useState('loading')
  const [response, setResponse]   = useState(null)
  const [error, setError]         = useState(null)
  const [latency, setLatency]     = useState(null)
  const [timestamp, setTimestamp] = useState(null)

  async function runCheck(signal) {
    const t0 = performance.now()
    try {
      const res = await fetch(`${API_URL}/api/health`, { signal })
      const ms  = Math.round(performance.now() - t0)

      if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`)

      const data = await res.json()
      setResponse(data)
      setLatency(ms)
      setTimestamp(new Date().toLocaleTimeString())
      setStatus('success')
    } catch (err) {
      if (err.name === 'AbortError') return
      setError(err.message || 'Unknown error')
      setLatency(Math.round(performance.now() - t0))
      setTimestamp(new Date().toLocaleTimeString())
      setStatus('error')
    }
  }

  function handleCheck() {
    setStatus('loading')
    setResponse(null)
    setError(null)
    setLatency(null)
    runCheck()
  }

  useEffect(() => {
    const controller = new AbortController()
    Promise.resolve().then(() => {
      if (!controller.signal.aborted) runCheck(controller.signal)
    })
    return () => controller.abort()
  }, [])

  const systemStatus = systemHealthLabel(status, response)
  const systemColor = systemStatus === 'OPERATIONAL'
    ? 'text-predix-emerald'
    : systemStatus === 'DEGRADED'
      ? 'text-predix-amber'
      : systemStatus === 'OFFLINE'
        ? 'text-predix-red'
        : 'text-predix-muted'

  return (
    <section aria-label="PREDIX system status" className="glass-card p-4 sm:px-5 animate-slide-up">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Radio className="h-4 w-4 text-predix-cyan" aria-hidden="true" />
          <h2 className="text-xs font-semibold tracking-wide text-white">PREDIX SYSTEM</h2>
          <span className={`inline-flex items-center gap-2 font-mono text-[10px] tracking-widest ${systemColor}`} aria-live="polite">
            <span className={`h-2 w-2 rounded-full ${systemStatus === 'OPERATIONAL' ? 'bg-predix-emerald' : systemStatus === 'DEGRADED' ? 'bg-predix-amber' : systemStatus === 'OFFLINE' ? 'bg-predix-red' : 'animate-pulse bg-predix-muted'}`} />
            {systemStatus}
          </span>
          {latency !== null && <span className="font-mono text-[10px] text-predix-muted">{latency} ms</span>}
        </div>
        <details className="group">
          <summary className="cursor-pointer list-none text-[10px] font-mono text-predix-cyan hover:text-white">System health details</summary>
          <div className="absolute left-4 right-4 z-20 mt-3 rounded-xl border border-predix-border bg-predix-bg p-4 shadow-2xl sm:left-auto sm:right-[max(1rem,calc((100vw-80rem)/2))] sm:w-[min(36rem,calc(100vw-2rem))]">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-xs font-semibold text-white">Advanced system health</h3>
                <p className="mt-1 text-[10px] font-mono text-predix-muted">{API_URL}/api/health</p>
              </div>
              <button
                id="check-system-btn"
                type="button"
                onClick={handleCheck}
                disabled={status === 'loading'}
                className="inline-flex items-center gap-1.5 rounded-lg border border-predix-cyan/30 px-3 py-2 text-[10px] font-semibold text-predix-cyan hover:bg-predix-cyan/10 disabled:opacity-40"
              >
                {status === 'loading'
                  ? <><Loader className="h-3.5 w-3.5 animate-spin" /> Checking</>
                  : <><ChevronRight className="h-3.5 w-3.5" /> Recheck</>}
              </button>
            </div>
            {response?.components && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label="PREDIX component health">
                {Object.entries(response.components).map(([name, component]) => {
                  const stateColor = component.status === 'ONLINE' ? 'text-predix-emerald' : component.status === 'DEGRADED' ? 'text-predix-amber' : 'text-predix-red'
                  return (
                    <div key={name} className="flex items-center justify-between gap-3 rounded-lg border border-predix-border bg-predix-surface/60 px-3 py-2">
                      <span className="text-xs capitalize text-predix-text">{name.replaceAll('_', ' ')}</span>
                      <span className={`shrink-0 font-mono text-[10px] ${stateColor}`}>{component.status}</span>
                    </div>
                  )
                })}
              </div>
            )}
            {response?.process_resources && (
              <div className="mt-3 rounded-lg border border-predix-border bg-predix-surface/40 p-3" aria-label="Process resource telemetry">
                <p className="text-[10px] font-mono text-predix-muted">PROCESS RESOURCE TELEMETRY · {response.process_resources.status.toUpperCase()}</p>
                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div><p className="text-[10px] text-predix-muted">CPU since previous health check</p><p className="font-mono text-xs text-white">{response.process_resources.process_cpu_percent_of_one_core == null ? 'Sampling…' : `${response.process_resources.process_cpu_percent_of_one_core}% of one core`}</p></div>
                  <div><p className="text-[10px] text-predix-muted">Peak process memory</p><p className="font-mono text-xs text-white">{response.process_resources.process_peak_rss_mb_since_start == null ? 'Unavailable' : `${response.process_resources.process_peak_rss_mb_since_start} MB`}</p></div>
                  <div><p className="text-[10px] text-predix-muted">PyTorch MPS allocated memory</p><p className="font-mono text-xs text-white">{response.process_resources.mps_allocated_mb == null ? 'Not reported' : `${response.process_resources.mps_allocated_mb} MB`}</p></div>
                </div>
                <p className="mt-2 text-[10px] text-predix-muted">CPU is sampled between health requests and can exceed 100% when multithreaded. Memory is the process high-water mark since start. MPS reports allocated tensors, not total device utilization.</p>
              </div>
            )}
            {error && <p role="alert" className="mt-3 text-xs text-predix-red">Health check failed: {error}</p>}
            {response && <p className="mt-3 text-[10px] text-predix-muted">Last checked {timestamp}. AI engine {response.components?.ai_engine?.model_state?.toLowerCase() || 'status unavailable'}.</p>}
            {response && <details className="mt-3 rounded-lg border border-predix-border bg-predix-surface/40 p-3">
              <summary className="cursor-pointer text-[10px] font-mono text-predix-muted">Raw health response</summary>
              <pre className="mt-3 overflow-x-auto rounded-lg border border-predix-border bg-predix-bg p-3 font-mono text-[10px] leading-relaxed text-predix-muted">{JSON.stringify(response, null, 2)}</pre>
            </details>}
          </div>
        </details>
      </div>
    </section>
  )
}
