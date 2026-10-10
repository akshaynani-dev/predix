import { Activity } from 'lucide-react'
import { useEffect, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function Header() {
  const [systemStatus, setSystemStatus] = useState('checking')

  useEffect(() => {
    const controller = new AbortController()
    fetch(`${API_URL}/api/health`, { signal: controller.signal })
      .then(async (response) => {
        const data = await response.json()
        if (!response.ok) throw new Error('Health endpoint unavailable')
        setSystemStatus(data.status === 'online' ? 'online' : 'degraded')
      })
      .catch((error) => {
        if (error.name !== 'AbortError') setSystemStatus('offline')
      })
    return () => controller.abort()
  }, [])

  const indicator = {
    online: ['bg-predix-emerald', 'text-predix-emerald', 'SYSTEM OPERATIONAL'],
    degraded: ['bg-predix-amber', 'text-predix-amber', 'SYSTEM DEGRADED'],
    offline: ['bg-predix-red', 'text-predix-red', 'SYSTEM OFFLINE'],
    checking: ['bg-predix-muted', 'text-predix-muted', 'CHECKING SYSTEM'],
  }[systemStatus]

  return (
    <header className="border-b border-predix-border bg-predix-surface/80 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-predix-cyan/10 border border-predix-cyan/30 flex items-center justify-center">
            <Activity className="w-5 h-5 text-predix-cyan" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-[0.15em] text-white text-glow-cyan">
              PREDIX
            </h1>
            <p className="text-[10px] font-mono tracking-widest text-predix-muted uppercase">
              Real-Time Predictive Intelligence
            </p>
          </div>
        </div>

        {/* System Status */}
        <div aria-label={`PREDIX ${indicator[2]}`} className="flex items-center gap-2 rounded-full border border-predix-border bg-predix-surface px-3 py-1.5">
          <span className={`status-dot ${indicator[0]}`} />
          <span className={`label-mono text-[10px] ${indicator[1]}`}>PREDIX · {indicator[2]}</span>
        </div>
      </div>
    </header>
  )
}
