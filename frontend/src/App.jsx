import { useState } from 'react'
import Header from './components/Header'
import MetricCards from './components/MetricCards'
import SystemCheck from './components/SystemCheck'
import VideoUpload from './components/VideoUpload'
import VideoAnalysis from './components/VideoAnalysis'
import LiveCamera from './components/LiveCamera'

export default function App() {
  const [stagedVideo, setStagedVideo] = useState(null)
  const [stagedPreviewUrl, setStagedPreviewUrl] = useState(null)
  const [inputMode, setInputMode] = useState('upload')

  function handleVideoUploaded(backendResponse, previewUrl) {
    setStagedVideo(backendResponse)
    setStagedPreviewUrl(previewUrl)
  }

  function handleVideoRemoved() {
    setStagedVideo(null)
    setStagedPreviewUrl(null)
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Header />

      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6 sm:py-10 space-y-8 sm:space-y-10">
        <section className="space-y-3" aria-labelledby="platform-title">
          <span className="label-mono text-[10px] text-predix-cyan">VIDEO INTELLIGENCE WORKSPACE</span>
          <h2 id="platform-title" className="max-w-3xl text-2xl sm:text-3xl font-bold tracking-tight text-white">
            From video to operational insight
          </h2>
          <p className="max-w-3xl text-sm leading-relaxed text-predix-muted">
            Analyze uploaded footage, inspect observed activity by time and zone, and compare it with stored sessions. Predictions appear only when compatible history is sufficient.
          </p>
        </section>

        <MetricCards inputMode={inputMode} />

        <div role="tablist" aria-label="Video input mode" className="grid grid-cols-2 gap-2 rounded-xl border border-predix-border bg-predix-surface/60 p-1.5 sm:inline-grid sm:w-auto">
          {[
            ['live', 'Live Camera'],
            ['upload', 'Upload Footage'],
          ].map(([mode, label]) => (
            <button
              key={mode}
              type="button"
              role="tab"
              aria-selected={inputMode === mode}
              onClick={() => setInputMode(mode)}
              className={`min-h-11 rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${inputMode === mode ? 'bg-predix-cyan text-predix-bg' : 'text-predix-muted hover:bg-predix-surface hover:text-white'}`}
            >
              {label}
            </button>
          ))}
        </div>

        <div hidden={inputMode !== 'upload'}>
          <VideoUpload
            onVideoUploaded={handleVideoUploaded}
            onVideoRemoved={handleVideoRemoved}
          />
        </div>

        {inputMode === 'live' && <LiveCamera />}

        {stagedVideo && (
          inputMode === 'upload' && <VideoAnalysis
            key={stagedVideo.video_id}
            uploadedVideo={stagedVideo}
            originalPreviewUrl={stagedPreviewUrl}
          />
        )}

        <div>
          <SystemCheck />
        </div>

      </main>

      {/* Footer */}
      <footer className="border-t border-predix-border py-4 px-6">
        <div className="max-w-7xl mx-auto flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-mono text-[10px] text-predix-muted/50 tracking-widest uppercase">
            PREDIX — Video intelligence workspace
          </span>
          <span className="font-mono text-[10px] text-predix-muted/40">
            Estimates require sufficient compatible history
          </span>
        </div>
      </footer>
    </div>
  )
}
