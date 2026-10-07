import { Activity } from 'lucide-react'

export default function Header() {
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
        <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-predix-cyan/5 border border-predix-cyan/20">
          <span className="status-dot bg-predix-cyan" />
          <span className="label-mono text-predix-cyan text-[10px]">LOCAL VIDEO ANALYTICS</span>
        </div>
      </div>
    </header>
  )
}
