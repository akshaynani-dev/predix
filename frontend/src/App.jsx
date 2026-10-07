import { useState } from 'react'
import Header from './components/Header'
import MetricCards from './components/MetricCards'
import SystemCheck from './components/SystemCheck'
import VideoUpload from './components/VideoUpload'
import VideoAnalysis from './components/VideoAnalysis'

export default function App() {
  const [stagedVideo, setStagedVideo] = useState(null)
  const [stagedPreviewUrl, setStagedPreviewUrl] = useState(null)

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

        <MetricCards />

        <VideoUpload
          onVideoUploaded={handleVideoUploaded}
          onVideoRemoved={handleVideoRemoved}
        />

        {stagedVideo && (
          <VideoAnalysis
            key={stagedVideo.video_id}
            uploadedVideo={stagedVideo}
            originalPreviewUrl={stagedPreviewUrl}
          />
        )}

        <div className="max-w-xl">
          <SystemCheck />
        </div>

      </main>

      {/* Footer */}
      <footer className="border-t border-predix-border py-4 px-6">
        <div className="max-w-7xl mx-auto flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <span className="font-mono text-[10px] text-predix-muted/50 tracking-widest uppercase">
            PREDIX — Uploaded video workflow
          </span>
          <span className="font-mono text-[10px] text-predix-muted/40">
            Estimates require sufficient compatible history
          </span>
        </div>
      </footer>
    </div>
  )
}
