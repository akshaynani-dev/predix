import { ScanLine, ListTree, ChartNoAxesCombined, Lightbulb } from 'lucide-react'

const stages = [
  {
    id: 'video-observations',
    icon: ScanLine,
    title: 'Video observations',
    description: 'Object detections are tied to sampled frames.',
    iconColor: 'text-predix-cyan',
  },
  {
    id: 'structured-events',
    icon: ListTree,
    title: 'Structured events',
    description: 'Frame detections become timestamped event records.',
    iconColor: 'text-predix-emerald',
  },
  {
    id: 'time-and-zone-analytics',
    icon: ChartNoAxesCombined,
    title: 'Time and zone analytics',
    description: 'Inspect observed activity across configured regions.',
    iconColor: 'text-predix-amber',
  },
  {
    id: 'historical-intelligence',
    icon: Lightbulb,
    title: 'Historical intelligence',
    description: 'Patterns, estimates, and advisory support require enough comparable sessions.',
    iconColor: 'text-predix-cyan',
  },
]

export default function MetricCards() {
  return (
    <section aria-label="Analysis pipeline">
      <div className="flex items-center gap-2 mb-4">
        <span className="label-mono text-predix-muted text-[11px]">Analysis pipeline</span>
        <div className="flex-1 h-px bg-predix-border" />
        <span className="text-[10px] font-mono text-predix-muted">Results are generated from uploaded video</span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        {stages.map(({ id, icon: Icon, title, description, iconColor }) => (
          <div
            key={id}
            id={id}
            className="glass-card p-4 sm:p-5"
          >
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-lg bg-predix-surface border border-predix-border flex items-center justify-center ${iconColor}`}>
                <Icon className="w-5 h-5" />
              </div>
              <h3 className="text-sm font-semibold text-white">{title}</h3>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-predix-muted">{description}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
