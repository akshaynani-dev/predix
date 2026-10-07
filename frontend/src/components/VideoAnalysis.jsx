import { useState, useEffect, useRef } from 'react'
import {
  Brain,
  Play,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Layers,
  Gauge,
  Film,
  User,
  Car,
  Bus,
  Truck,
  Bike,
  Sparkles,
  Info,
} from 'lucide-react'
import DigitalTwin from './DigitalTwin'
import AnalyticsDashboard from './AnalyticsDashboard'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const ANALYSIS_STATES = {
  READY: 'READY',
  ANALYZING: 'ANALYZING',
  COMPLETED: 'COMPLETED',
  ERROR: 'ERROR',
}

const CLASS_ICONS = {
  person: User,
  car: Car,
  bus: Bus,
  truck: Truck,
  motorcycle: Bike,
  bicycle: Bike,
}

export default function VideoAnalysis({ uploadedVideo, originalPreviewUrl }) {
  const [analysisState, setAnalysisState] = useState(ANALYSIS_STATES.READY)
  const [jobStatus, setJobStatus] = useState(null)
  const [analysisResult, setAnalysisResult] = useState(null)
  const [errorMessage, setErrorMessage] = useState(null)
  const [activePlayerTab, setActivePlayerTab] = useState('annotated') // 'annotated' | 'original'

  const pollIntervalRef = useRef(null)

  // Clear polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  async function pollStatus(videoId) {
    try {
      const res = await fetch(`${API_URL}/api/video/${videoId}/analysis/status`)
      if (!res.ok) {
        throw new Error(`Status check failed: HTTP ${res.status}`)
      }
      const data = await res.json()
      setJobStatus(data)

      if (data.status === 'completed') {
        // Stop polling immediately
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current)
          pollIntervalRef.current = null
        }
        // Fetch full results
        await fetchResults(videoId)
      } else if (data.status === 'error') {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current)
          pollIntervalRef.current = null
        }
        setErrorMessage(data.error || 'Video analysis encountered an error.')
        setAnalysisState(ANALYSIS_STATES.ERROR)
      }
    } catch (err) {
      console.warn('Status poll error:', err)
    }
  }

  async function fetchResults(videoId) {
    try {
      const res = await fetch(`${API_URL}/api/video/${videoId}/analysis/result`)
      if (!res.ok) {
        throw new Error(`Failed to retrieve results: HTTP ${res.status}`)
      }
      const data = await res.json()
      setAnalysisResult(data)
      setAnalysisState(ANALYSIS_STATES.COMPLETED)
    } catch (err) {
      setErrorMessage(err.message || 'Failed to retrieve analysis statistics.')
      setAnalysisState(ANALYSIS_STATES.ERROR)
    }
  }

  async function handleStartAnalysis() {
    if (!uploadedVideo?.video_id || analysisState === ANALYSIS_STATES.ANALYZING) return

    setAnalysisState(ANALYSIS_STATES.ANALYZING)
    setErrorMessage(null)
    setJobStatus({
      progress_percentage: 0,
      frames_processed: 0,
      total_frames: 0,
      elapsed_time_seconds: 0,
      device_name: 'Detecting...',
      model: 'yolo11n.pt',
    })

    try {
      const res = await fetch(`${API_URL}/api/video/${uploadedVideo.video_id}/analyze`, {
        method: 'POST',
      })

      if (res.status === 409) {
        // Analysis already running, attach to polling
        setAnalysisState(ANALYSIS_STATES.ANALYZING)
      } else if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.detail || `Server error: HTTP ${res.status}`)
      }

      // Start polling every 1.5s
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = setInterval(() => {
        pollStatus(uploadedVideo.video_id)
      }, 1500)

      // Initial immediate check
      pollStatus(uploadedVideo.video_id)
    } catch (err) {
      setErrorMessage(err.message || 'Could not start analysis.')
      setAnalysisState(ANALYSIS_STATES.ERROR)
    }
  }

  const annotatedVideoUrl = uploadedVideo?.video_id
    ? `${API_URL}/api/video/${uploadedVideo.video_id}/annotated`
    : null

  return (
    <>
    <section aria-label="Computer Vision Analysis" className="glass-card p-6 md:p-8 animate-slide-up border-predix-cyan/20">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-predix-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-predix-cyan/10 border border-predix-cyan/30 flex items-center justify-center">
            <Brain className="w-5 h-5 text-predix-cyan" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white tracking-wide">Computer Vision Engine</h2>
            </div>
            <p className="text-xs text-predix-muted mt-0.5">
              Pretrained YOLO object detection &amp; frame-level instance accumulation
            </p>
          </div>
        </div>

        {/* Status Badge */}
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span className="text-[11px] font-mono text-predix-muted uppercase tracking-wider">Status:</span>
          {analysisState === ANALYSIS_STATES.READY && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-surface border border-predix-border text-predix-cyan flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" /> READY FOR ANALYSIS
            </span>
          )}
          {analysisState === ANALYSIS_STATES.ANALYZING && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-cyan/10 border border-predix-cyan/30 text-predix-cyan flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> ANALYZING {jobStatus?.progress_percentage || 0}%
            </span>
          )}
          {analysisState === ANALYSIS_STATES.COMPLETED && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-emerald/10 border border-predix-emerald/30 text-predix-emerald flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" /> ANALYSIS COMPLETED
            </span>
          )}
          {analysisState === ANALYSIS_STATES.ERROR && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-red/10 border border-predix-red/30 text-predix-red flex items-center gap-1.5">
              <AlertTriangle className="w-3.5 h-3.5" /> ANALYSIS ERROR
            </span>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="mt-6 space-y-6">
        {/* Error Alert */}
        {errorMessage && (
          <div className="p-4 rounded-xl bg-predix-red/10 border border-predix-red/30 flex items-start gap-3 animate-fade-in">
            <AlertTriangle className="w-5 h-5 text-predix-red shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-xs font-semibold text-predix-red tracking-wide uppercase font-mono">
                Analysis Notification
              </h4>
              <p className="text-xs text-predix-text/90 mt-0.5">{errorMessage}</p>
            </div>
            <button
              type="button"
              onClick={handleStartAnalysis}
              className="text-xs font-mono text-predix-cyan hover:underline ml-auto shrink-0 uppercase"
            >
              Retry
            </button>
          </div>
        )}

        {/* ── STATE: READY ────────────────────────────────────────────── */}
        {analysisState === ANALYSIS_STATES.READY && (
          <div className="rounded-2xl border border-predix-border bg-predix-surface/40 p-8 text-center flex flex-col items-center justify-center animate-fade-in">
            <div className="w-14 h-14 rounded-2xl bg-predix-cyan/10 border border-predix-cyan/20 flex items-center justify-center mb-4">
              <Brain className="w-7 h-7 text-predix-cyan" />
            </div>

            <h3 className="text-base font-semibold text-white tracking-wide mb-1">
              Video Staged for Object Detection
            </h3>
            <p className="text-xs font-mono text-predix-muted max-w-md mb-6 truncate" title={uploadedVideo?.filename}>
              {uploadedVideo?.filename} ({uploadedVideo?.video_id})
            </p>

            {/* Inference Specs (Server Configuration) */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6 max-w-lg w-full text-left">
              <div className="p-3 rounded-lg bg-predix-surface border border-predix-border">
                <span className="label-mono text-[9px] text-predix-muted block mb-0.5">Model</span>
                <span className="text-xs font-mono text-predix-cyan font-semibold">YOLO Nano</span>
                <span className="text-[10px] font-mono text-predix-muted/70 block">yolo11n.pt</span>
              </div>
              <div className="p-3 rounded-lg bg-predix-surface border border-predix-border">
                <span className="label-mono text-[9px] text-predix-muted block mb-0.5">Device</span>
                <span className="text-xs font-mono text-white font-semibold">Auto (MPS / CPU)</span>
                <span className="text-[10px] font-mono text-predix-muted/70 block">Runtime Detection</span>
              </div>
              <div className="p-3 rounded-lg bg-predix-surface border border-predix-border col-span-2 sm:col-span-1">
                <span className="label-mono text-[9px] text-predix-muted block mb-0.5">Confidence</span>
                <span className="text-xs font-mono text-predix-emerald font-semibold">0.25 (25%)</span>
                <span className="text-[10px] font-mono text-predix-muted/70 block">COCO 80 classes</span>
              </div>
            </div>

            <button
              type="button"
              id="analyze-video-btn"
              onClick={handleStartAnalysis}
              className="flex items-center gap-2 px-8 py-3 rounded-lg bg-predix-cyan text-predix-bg font-semibold text-xs uppercase tracking-wider hover:bg-predix-cyan/90 hover:shadow-cyan transition-all active:scale-[0.98]"
            >
              <Play className="w-4 h-4 fill-current" /> Analyze Video
            </button>
          </div>
        )}

        {/* ── STATE: ANALYZING ────────────────────────────────────────── */}
        {analysisState === ANALYSIS_STATES.ANALYZING && (
          <div className="rounded-2xl border border-predix-border bg-predix-surface/40 p-8 space-y-6 animate-fade-in">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div className="flex items-center gap-3">
                <Loader2 className="w-5 h-5 text-predix-cyan animate-spin" />
                <div>
                  <h3 className="text-sm font-semibold text-white">Running Object Detection...</h3>
                  <p className="text-xs font-mono text-predix-muted">Streaming frame-by-frame inference</p>
                </div>
              </div>
              <div className="flex items-center gap-4 text-xs font-mono">
                <span className="text-predix-muted">
                  Device: <span className="text-predix-cyan">{jobStatus?.device_name || 'Detecting...'}</span>
                </span>
                <span className="text-predix-muted">
                  Model: <span className="text-white">{jobStatus?.model || 'yolo11n.pt'}</span>
                </span>
              </div>
            </div>

            {/* Progress bar */}
            <div>
              <div className="flex justify-between text-xs font-mono mb-2">
                <span className="text-white">
                  Frames: {jobStatus?.frames_processed || 0} / {jobStatus?.total_frames || '...'}
                </span>
                <span className="text-predix-cyan font-bold">
                  {jobStatus?.progress_percentage || 0}%
                </span>
              </div>
              <div className="w-full h-2.5 rounded-full bg-predix-bg overflow-hidden border border-predix-border">
                <div
                  className="h-full bg-predix-cyan transition-all duration-300"
                  style={{ width: `${jobStatus?.progress_percentage || 0}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] font-mono text-predix-muted mt-2">
                <span>Elapsed: {jobStatus?.elapsed_time_seconds || 0}s</span>
                <span>Batch Size: 1 • Resolution: 640px</span>
              </div>
            </div>
          </div>
        )}

        {/* ── STATE: COMPLETED ────────────────────────────────────────── */}
        {analysisState === ANALYSIS_STATES.COMPLETED && analysisResult && (
          <div className="space-y-6 animate-fade-in">
            {/* Player View Controls */}
            <div className="flex flex-wrap items-center justify-between gap-3 pb-2">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActivePlayerTab('annotated')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono uppercase tracking-wider transition-all ${
                    activePlayerTab === 'annotated'
                      ? 'bg-predix-cyan text-predix-bg font-semibold shadow-cyan'
                      : 'bg-predix-surface border border-predix-border text-predix-muted hover:text-white'
                  }`}
                >
                  AI Detection Result
                </button>
                <button
                  type="button"
                  onClick={() => setActivePlayerTab('original')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-mono uppercase tracking-wider transition-all ${
                    activePlayerTab === 'original'
                      ? 'bg-predix-cyan text-predix-bg font-semibold shadow-cyan'
                      : 'bg-predix-surface border border-predix-border text-predix-muted hover:text-white'
                  }`}
                >
                  Original Video
                </button>
              </div>

              <div className="flex items-center gap-3 text-[11px] font-mono">
                <span className="text-predix-muted">
                  Device: <span className="text-predix-emerald font-semibold">{analysisResult.device_name}</span>
                </span>
                <span className="text-predix-muted">•</span>
                <span className="text-predix-muted">
                  Speed: <span className="text-white font-semibold">{analysisResult.processing_fps} FPS</span>
                </span>
              </div>
            </div>

            {/* Video Player Display */}
            <div className="rounded-xl overflow-hidden bg-black/80 border border-predix-border aspect-video shadow-lg relative flex items-center justify-center">
              {activePlayerTab === 'annotated' ? (
                <video
                  key="annotated-player"
                  src={annotatedVideoUrl}
                  controls
                  className="w-full h-full object-contain"
                >
                  Your browser does not support annotated video playback.
                </video>
              ) : (
                <video
                  key="original-player"
                  src={originalPreviewUrl}
                  controls
                  className="w-full h-full object-contain"
                >
                  Your browser does not support video playback.
                </video>
              )}

              {/* Player Tag */}
              <div className="absolute top-3 left-3 px-2.5 py-1 rounded-md bg-predix-bg/80 backdrop-blur-md border border-predix-border text-[10px] font-mono tracking-widest uppercase">
                {activePlayerTab === 'annotated' ? (
                  <span className="text-predix-cyan flex items-center gap-1.5">
                    <Sparkles className="w-3 h-3" /> AI DETECTION RESULT
                  </span>
                ) : (
                  <span className="text-predix-muted flex items-center gap-1.5">
                    <Film className="w-3 h-3" /> ORIGINAL VIDEO
                  </span>
                )}
              </div>
            </div>

            {/* Detection Statistics Overview Cards */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="label-mono text-predix-muted text-[11px] flex items-center gap-1.5">
                  <Gauge className="w-3.5 h-3.5 text-predix-cyan" /> Detection Statistics (Frame-Level Instances)
                </span>
                <span className="text-[10px] font-mono text-predix-cyan">
                  Conf &ge; {Math.round(analysisResult.confidence_threshold * 100)}%
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-4 rounded-xl bg-predix-surface border border-predix-border">
                  <span className="label-mono text-[9px] text-predix-muted block mb-1">Frames Processed</span>
                  <p className="text-xl font-bold font-mono text-white">{analysisResult.frames_processed}</p>
                  <span className="text-[10px] font-mono text-predix-muted/60">Total: {analysisResult.total_frames}</span>
                </div>

                <div className="p-4 rounded-xl bg-predix-surface border border-predix-border">
                  <span className="label-mono text-[9px] text-predix-muted block mb-1">Total Detection Instances</span>
                  <p className="text-xl font-bold font-mono text-predix-cyan">{analysisResult.total_detection_instances}</p>
                  <span className="text-[10px] font-mono text-predix-muted/60">Accumulated occurrences</span>
                </div>

                <div className="p-4 rounded-xl bg-predix-surface border border-predix-border">
                  <span className="label-mono text-[9px] text-predix-muted block mb-1">Avg Instances / Frame</span>
                  <p className="text-xl font-bold font-mono text-predix-emerald">{analysisResult.average_instances_per_frame}</p>
                  <span className="text-[10px] font-mono text-predix-muted/60">Mean object instances per frame</span>
                </div>

                <div className="p-4 rounded-xl bg-predix-surface border border-predix-border">
                  <span className="label-mono text-[9px] text-predix-muted block mb-1">Processing Time</span>
                  <p className="text-xl font-bold font-mono text-white">{analysisResult.processing_time_seconds}s</p>
                  <span className="text-[10px] font-mono text-predix-muted/60">{analysisResult.processing_fps} FPS</span>
                </div>
              </div>
            </div>

            {/* Target Classes Breakdown */}
            <div>
              <span className="label-mono text-predix-muted text-[11px] block mb-3">
                Instances by Class
              </span>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                {['person', 'car', 'bus', 'truck', 'motorcycle', 'bicycle'].map((className) => {
                  const Icon = CLASS_ICONS[className] || Layers
                  const count = analysisResult.detection_instances_by_class?.[className] || 0
                  return (
                    <div
                      key={className}
                      className="p-3.5 rounded-xl bg-predix-surface/80 border border-predix-border flex flex-col justify-between"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <Icon className="w-4 h-4 text-predix-cyan" />
                        <span className="text-[9px] font-mono uppercase text-predix-muted tracking-wider">
                          {className}
                        </span>
                      </div>
                      <div>
                        <p className="text-lg font-bold font-mono text-white">{count}</p>
                        <span className="text-[9px] font-mono text-predix-muted/60">instances</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Other Classes (if any detected) */}
            {Object.entries(analysisResult.detection_instances_by_class || {})
              .filter(([cls]) => !['person', 'car', 'bus', 'truck', 'motorcycle', 'bicycle'].includes(cls))
              .length > 0 && (
              <div className="p-3 rounded-lg bg-predix-surface border border-predix-border text-xs font-mono">
                <span className="text-predix-muted mr-2">Other Detected Classes:</span>
                {Object.entries(analysisResult.detection_instances_by_class)
                  .filter(([cls]) => !['person', 'car', 'bus', 'truck', 'motorcycle', 'bicycle'].includes(cls))
                  .map(([cls, cnt]) => (
                    <span key={cls} className="mr-3 text-white">
                      {cls}: <strong className="text-predix-cyan">{cnt}</strong>
                    </span>
                  ))}
              </div>
            )}

            {/* Mandatory Scope Disclaimer Banner */}
            <div className="p-4 rounded-xl bg-predix-surface border border-predix-amber/30 flex items-start gap-3">
              <Info className="w-5 h-5 text-predix-amber shrink-0 mt-0.5" />
              <p className="text-xs font-mono text-predix-text/90 leading-relaxed">
                <strong className="text-predix-amber uppercase block mb-0.5">Detection scope</strong>
                Counts represent frame-level detection instances, not unique objects. This workflow does not track entities across frames.
              </p>
            </div>
          </div>
        )}
      </div>
    </section>
    <DigitalTwin
      videoId={uploadedVideo.video_id}
      sourcePreviewUrl={originalPreviewUrl}
      analysisState={analysisState}
    />
    {analysisState === ANALYSIS_STATES.COMPLETED && analysisResult && (
      <AnalyticsDashboard
        videoId={uploadedVideo.video_id}
        analysisResult={analysisResult}
        videoMetadata={uploadedVideo.metadata}
      />
    )}
    </>
  )
}
