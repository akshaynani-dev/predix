import { useState } from 'react'
import { Radio, CheckCircle, XCircle, Loader, ChevronRight } from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const STATUS = {
  IDLE:     'idle',
  LOADING:  'loading',
  SUCCESS:  'success',
  ERROR:    'error',
}

const statusConfig = {
  [STATUS.IDLE]:    { label: 'Idle',       color: 'text-predix-muted',   borderColor: 'border-predix-border',        bg: 'bg-predix-surface' },
  [STATUS.LOADING]: { label: 'Checking…',  color: 'text-predix-cyan',    borderColor: 'border-predix-cyan/40',       bg: 'bg-predix-cyan/5' },
  [STATUS.SUCCESS]: { label: 'Connected',  color: 'text-predix-emerald', borderColor: 'border-predix-emerald/40',    bg: 'bg-predix-emerald/5' },
  [STATUS.ERROR]:   { label: 'Error',      color: 'text-predix-red',     borderColor: 'border-predix-red/40',        bg: 'bg-predix-red/5' },
}

export default function SystemCheck() {
  const [status, setStatus]       = useState(STATUS.IDLE)
  const [response, setResponse]   = useState(null)
  const [error, setError]         = useState(null)
  const [latency, setLatency]     = useState(null)
  const [timestamp, setTimestamp] = useState(null)

  async function handleCheck() {
    setStatus(STATUS.LOADING)
    setResponse(null)
    setError(null)
    setLatency(null)

    const t0 = performance.now()
    try {
      const res = await fetch(`${API_URL}/api/health`)
      const ms  = Math.round(performance.now() - t0)

      if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText}`)

      const data = await res.json()
      setResponse(data)
      setLatency(ms)
      setTimestamp(new Date().toLocaleTimeString())
      setStatus(STATUS.SUCCESS)
    } catch (err) {
      setError(err.message || 'Unknown error')
      setLatency(Math.round(performance.now() - t0))
      setTimestamp(new Date().toLocaleTimeString())
      setStatus(STATUS.ERROR)
    }
  }

  const cfg = statusConfig[status]

  return (
    <section aria-label="Backend System Check" className="glass-card p-6 animate-slide-up">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div className="w-9 h-9 rounded-lg bg-predix-cyan/10 border border-predix-cyan/20 flex items-center justify-center">
          <Radio className="w-4 h-4 text-predix-cyan" />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-white tracking-wide">Backend Connection</h2>
          <p className="text-[11px] font-mono text-predix-muted">{API_URL}/api/health</p>
        </div>
      </div>

      {/* Status bar */}
      <div className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border mb-5 transition-all duration-300 ${cfg.borderColor} ${cfg.bg}`}>
        {status === STATUS.LOADING && <Loader className={`w-4 h-4 animate-spin ${cfg.color}`} />}
        {status === STATUS.SUCCESS && <CheckCircle className={`w-4 h-4 ${cfg.color}`} />}
        {status === STATUS.ERROR   && <XCircle    className={`w-4 h-4 ${cfg.color}`} />}
        {status === STATUS.IDLE    && <span className={`status-dot bg-predix-muted`} />}
        <span className={`font-mono text-xs tracking-widest uppercase ${cfg.color}`}>
          {cfg.label}
        </span>
        {latency !== null && (
          <span className="ml-auto font-mono text-[10px] text-predix-muted">{latency} ms</span>
        )}
        {timestamp && (
          <span className="font-mono text-[10px] text-predix-muted/60">{timestamp}</span>
        )}
      </div>

      {/* Check button */}
      <button
        id="check-system-btn"
        onClick={handleCheck}
        disabled={status === STATUS.LOADING}
        className="w-full flex items-center justify-center gap-2 px-6 py-3 rounded-lg font-semibold text-sm tracking-wide transition-all duration-200
          bg-predix-cyan text-predix-bg hover:bg-predix-cyan/90 hover:shadow-cyan active:scale-[0.98]
          disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-predix-cyan"
      >
        {status === STATUS.LOADING
          ? <><Loader className="w-4 h-4 animate-spin" /> Checking…</>
          : <><ChevronRight className="w-4 h-4" /> CHECK SYSTEM</>
        }
      </button>

      {/* Response viewer */}
      {(response || error) && (
        <div className="mt-5 animate-fade-in">
          <p className="label-mono text-predix-muted text-[10px] mb-2">Response Payload</p>
          <pre className={`font-mono text-xs rounded-lg p-4 border overflow-x-auto leading-relaxed
            ${status === STATUS.SUCCESS
              ? 'bg-predix-emerald/5 border-predix-emerald/20 text-predix-emerald'
              : 'bg-predix-red/5 border-predix-red/20 text-predix-red'
            }`}>
            {status === STATUS.SUCCESS
              ? JSON.stringify(response, null, 2)
              : `Error: ${error}`
            }
          </pre>
        </div>
      )}
    </section>
  )
}
