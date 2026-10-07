import { useState, useRef, useEffect } from 'react'
import {
  UploadCloud,
  Film,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Trash2,
  FileVideo,
  Clock,
  Maximize2,
  HardDrive,
  Loader2,
  ArrowUpRight,
  RefreshCw,
} from 'lucide-react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const MAX_UPLOAD_BYTES = Number(import.meta.env.VITE_MAX_UPLOAD_SIZE_BYTES) || 1073741824 // 1 GB default
const ALLOWED_EXTENSIONS = ['.mp4', '.webm', '.mov']
const ALLOWED_MIME_PREFIX = 'video/'

const UPLOAD_STATES = {
  IDLE: 'IDLE',
  SELECTED: 'SELECTED',
  UPLOADING: 'UPLOADING',
  UPLOADED: 'UPLOADED',
  ERROR: 'ERROR',
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

function formatDuration(seconds) {
  if (!seconds || isNaN(seconds) || seconds === Infinity) return 'Calculating...'
  const totalSeconds = Math.floor(seconds)
  const hrs = Math.floor(totalSeconds / 3600)
  const mins = Math.floor((totalSeconds % 3600) / 60)
  const secs = totalSeconds % 60

  if (hrs > 0) {
    return `${hrs.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
}

export default function VideoUpload({ onVideoUploaded, onVideoRemoved }) {
  const [uploadState, setUploadState] = useState(UPLOAD_STATES.IDLE)
  const [selectedFile, setSelectedFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [videoDimensions, setVideoDimensions] = useState(null)
  const [videoDuration, setVideoDuration] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploadedBytes, setUploadedBytes] = useState(0)
  const [backendResponse, setBackendResponse] = useState(null)
  const [errorMessage, setErrorMessage] = useState(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  const fileInputRef = useRef(null)
  const videoRef = useRef(null)
  const xhrRef = useRef(null)
  const serverMetadata = backendResponse?.metadata

  // Clean up object URLs to prevent memory leaks
  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl)
      }
      if (xhrRef.current) {
        xhrRef.current.abort()
      }
    }
  }, [previewUrl])

  function validateFile(file) {
    if (!file) {
      return 'No file selected.'
    }

    const filename = file.name || ''
    const ext = '.' + filename.split('.').pop().toLowerCase()

    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return 'Unsupported video format. Please upload MP4, WebM, or MOV.'
    }

    if (file.type && !file.type.startsWith(ALLOWED_MIME_PREFIX) && file.type !== 'video/quicktime') {
      return 'Unsupported video format. Please upload MP4, WebM, or MOV.'
    }

    if (file.size > MAX_UPLOAD_BYTES) {
      return `Video exceeds the maximum allowed upload size (${formatBytes(MAX_UPLOAD_BYTES)}).`
    }

    return null
  }

  function handleFileSelection(file) {
    if (!file) return

    // Validate
    const error = validateFile(file)
    if (error) {
      setErrorMessage(error)
      setUploadState(UPLOAD_STATES.ERROR)
      setSelectedFile(null)
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl)
        setPreviewUrl(null)
      }
      return
    }

    // Reset previous state
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
    }

    const objectUrl = URL.createObjectURL(file)
    setSelectedFile(file)
    setPreviewUrl(objectUrl)
    setVideoDimensions(null)
    setVideoDuration(null)
    setUploadProgress(0)
    setUploadedBytes(0)
    setBackendResponse(null)
    setErrorMessage(null)
    setUploadState(UPLOAD_STATES.SELECTED)
  }

  function onFileInputChange(e) {
    const file = e.target.files?.[0]
    if (file) {
      handleFileSelection(file)
    }
  }

  function handleDragOver(e) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }

  function handleDragLeave(e) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }

  function handleDrop(e) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)

    const files = e.dataTransfer?.files
    if (files && files.length > 0) {
      handleFileSelection(files[0])
    }
  }

  function handleLoadedMetadata(e) {
    const target = e.currentTarget
    if (target.videoWidth && target.videoHeight) {
      setVideoDimensions(`${target.videoWidth} × ${target.videoHeight}`)
    }
    if (target.duration) {
      setVideoDuration(target.duration)
    }
  }

  async function handleUpload() {
    if (!selectedFile || uploadState === UPLOAD_STATES.UPLOADING) return

    setUploadState(UPLOAD_STATES.UPLOADING)
    setUploadProgress(0)
    setUploadedBytes(0)
    setErrorMessage(null)

    const formData = new FormData()
    formData.append('file', selectedFile)

    const xhr = new XMLHttpRequest()
    xhrRef.current = xhr

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100)
        setUploadProgress(percent)
        setUploadedBytes(event.loaded)
      }
    }

    xhr.onload = () => {
      xhrRef.current = null
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const response = JSON.parse(xhr.responseText)
          setBackendResponse(response)
          setUploadProgress(100)
          setUploadState(UPLOAD_STATES.UPLOADED)
          onVideoUploaded?.(response, previewUrl)
        } catch {
          setErrorMessage('Invalid server response format.')
          setUploadState(UPLOAD_STATES.ERROR)
        }
      } else {
        let message = 'Upload failed. Please try again.'
        try {
          const errorData = JSON.parse(xhr.responseText)
          if (errorData.detail) {
            message = errorData.detail
          }
        } catch {
          if (xhr.status === 413) {
            message = 'Video exceeds the maximum allowed upload size.'
          } else if (xhr.status === 0) {
            message = 'Unable to connect to the PREDIX server.'
          }
        }
        setErrorMessage(message)
        setUploadState(UPLOAD_STATES.ERROR)
      }
    }

    xhr.onerror = () => {
      xhrRef.current = null
      setErrorMessage('Unable to connect to the PREDIX server.')
      setUploadState(UPLOAD_STATES.ERROR)
    }

    xhr.onabort = () => {
      xhrRef.current = null
    }

    try {
      xhr.open('POST', `${API_URL}/api/video/upload`, true)
      xhr.send(formData)
    } catch {
      setErrorMessage('Unable to connect to the PREDIX server.')
      setUploadState(UPLOAD_STATES.ERROR)
    }
  }

  async function handleResetOrRemove() {
    // If currently uploading, abort XHR
    if (xhrRef.current) {
      xhrRef.current.abort()
      xhrRef.current = null
    }

    // If already uploaded and we have a video_id, clean up from server
    if (backendResponse?.video_id) {
      setIsDeleting(true)
      try {
        await fetch(`${API_URL}/api/video/${backendResponse.video_id}`, {
          method: 'DELETE',
        })
      } catch (err) {
        console.warn('Failed to delete temporary video on server:', err)
      } finally {
        setIsDeleting(false)
      }
    }

    // Clean up local preview URL
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl)
    }

    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }

    setSelectedFile(null)
    setPreviewUrl(null)
    setVideoDimensions(null)
    setVideoDuration(null)
    setUploadProgress(0)
    setUploadedBytes(0)
    setBackendResponse(null)
    setErrorMessage(null)
    setUploadState(UPLOAD_STATES.IDLE)
    onVideoRemoved?.()
  }

  return (
    <section aria-label="Video Input Pipeline" className="glass-card p-6 md:p-8 animate-slide-up">
      {/* Section Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-6 border-b border-predix-border">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-predix-cyan/10 border border-predix-cyan/20 flex items-center justify-center">
            <Film className="w-5 h-5 text-predix-cyan" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-white tracking-wide">Video Input Pipeline</h2>
            </div>
            <p className="text-xs text-predix-muted mt-0.5">
              Select a clip to validate, preview, upload, and analyze
            </p>
          </div>
        </div>

        {/* State Badge */}
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span className="text-[11px] font-mono text-predix-muted uppercase tracking-wider">Status:</span>
          {uploadState === UPLOAD_STATES.IDLE && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-surface border border-predix-border text-predix-muted">
              IDLE
            </span>
          )}
          {uploadState === UPLOAD_STATES.SELECTED && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-amber/10 border border-predix-amber/30 text-predix-amber">
              SELECTED
            </span>
          )}
          {uploadState === UPLOAD_STATES.UPLOADING && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-cyan/10 border border-predix-cyan/30 text-predix-cyan flex items-center gap-1.5">
              <Loader2 className="w-3 h-3 animate-spin" /> UPLOADING {uploadProgress}%
            </span>
          )}
          {uploadState === UPLOAD_STATES.UPLOADED && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-emerald/10 border border-predix-emerald/30 text-predix-emerald flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5" /> STAGED / UPLOADED
            </span>
          )}
          {uploadState === UPLOAD_STATES.ERROR && (
            <span className="px-2.5 py-1 rounded-md text-xs font-mono bg-predix-red/10 border border-predix-red/30 text-predix-red flex items-center gap-1.5">
              <XCircle className="w-3.5 h-3.5" /> ERROR
            </span>
          )}
        </div>
      </div>

      {/* Main Body */}
      <div className="mt-6 space-y-6">
        {/* Hidden native input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".mp4,.webm,.mov,video/mp4,video/webm,video/quicktime"
          onChange={onFileInputChange}
          className="hidden"
          id="predix-video-input"
        />

        {/* ── STATE 1: IDLE or ERROR (without selected video) ───────────── */}
        {uploadState === UPLOAD_STATES.IDLE || (uploadState === UPLOAD_STATES.ERROR && !selectedFile) ? (
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`cursor-pointer rounded-2xl border-2 border-dashed p-10 md:p-14 text-center transition-all duration-300 flex flex-col items-center justify-center group ${
              isDragOver
                ? 'border-predix-cyan bg-predix-cyan/10 shadow-cyan scale-[1.005]'
                : 'border-predix-border/70 hover:border-predix-cyan/50 hover:bg-predix-surface/60 bg-predix-surface/30'
            }`}
          >
            <div className="w-16 h-16 rounded-2xl bg-predix-surface border border-predix-border flex items-center justify-center mb-5 group-hover:border-predix-cyan/40 group-hover:scale-105 transition-all">
              <UploadCloud className="w-8 h-8 text-predix-cyan transition-transform group-hover:-translate-y-0.5" />
            </div>

            <h3 className="text-base md:text-lg font-semibold text-white tracking-wide mb-1">
              UPLOAD VIDEO
            </h3>
            <p className="text-sm text-predix-muted mb-4 max-w-sm">
              Drop a video here or browse your files from your Mac
            </p>

            <div className="flex items-center gap-2 mb-6">
              <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-predix-surface border border-predix-border text-predix-text/80">
                MP4
              </span>
              <span className="text-predix-muted text-xs">•</span>
              <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-predix-surface border border-predix-border text-predix-text/80">
                WebM
              </span>
              <span className="text-predix-muted text-xs">•</span>
              <span className="px-2.5 py-1 rounded-md text-[11px] font-mono bg-predix-surface border border-predix-border text-predix-text/80">
                MOV
              </span>
            </div>

            <button
              type="button"
              id="browse-files-btn"
              onClick={(e) => {
                e.stopPropagation()
                fileInputRef.current?.click()
              }}
              className="px-6 py-2.5 rounded-lg bg-predix-cyan text-predix-bg font-semibold text-xs tracking-wider uppercase hover:bg-predix-cyan/90 hover:shadow-cyan transition-all active:scale-[0.98]"
            >
              Browse Files
            </button>

            <p className="text-[11px] font-mono text-predix-muted/60 mt-4">
              Maximum upload limit: {formatBytes(MAX_UPLOAD_BYTES)} (Configurable)
            </p>
          </div>
        ) : null}

        {/* ── ERROR BANNER (when error occurs) ─────────────────────────── */}
        {errorMessage && (
          <div className="p-4 rounded-xl bg-predix-red/10 border border-predix-red/30 flex items-start gap-3 animate-fade-in">
            <AlertTriangle className="w-5 h-5 text-predix-red shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-xs font-semibold text-predix-red tracking-wide uppercase font-mono">
                Validation / Upload Alert
              </h4>
              <p className="text-xs text-predix-text/90 mt-0.5">{errorMessage}</p>
            </div>
            {uploadState === UPLOAD_STATES.ERROR && (
              <button
                type="button"
                onClick={handleResetOrRemove}
                className="text-xs font-mono text-predix-red hover:underline ml-auto shrink-0"
              >
                Dismiss
              </button>
            )}
          </div>
        )}

        {/* ── PREVIEW + METADATA + ACTIONS (SELECTED, UPLOADING, UPLOADED) ── */}
        {previewUrl && (
          <div className="space-y-6 animate-fade-in">
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              {/* Native Video Player Container */}
              <div className="lg:col-span-7 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <span className="label-mono text-predix-muted text-[11px] flex items-center gap-1.5">
                    <Film className="w-3.5 h-3.5 text-predix-cyan" /> Video Preview
                  </span>
                  <span className="text-[10px] font-mono text-predix-muted/70">
                    Native Browser Player (No Frame Processing)
                  </span>
                </div>

                <div className="relative rounded-xl overflow-hidden bg-black/80 border border-predix-border aspect-video flex items-center justify-center shadow-lg group">
                  <video
                    ref={videoRef}
                    src={previewUrl}
                    controls
                    preload="metadata"
                    onLoadedMetadata={handleLoadedMetadata}
                    className="w-full h-full object-contain"
                  >
                    Your browser does not support the video tag.
                  </video>
                </div>
              </div>

              {/* Video Metadata Panel */}
              <div className="lg:col-span-5 flex flex-col">
                <div className="flex items-center justify-between mb-2">
                  <span className="label-mono text-predix-muted text-[11px] flex items-center gap-1.5">
                    <FileVideo className="w-3.5 h-3.5 text-predix-cyan" /> Video Information
                  </span>
                  <span className="text-[10px] font-mono text-predix-emerald">
                    {serverMetadata ? 'Validated by PREDIX' : 'Browser preview'}
                  </span>
                </div>

                <div className="flex-1 rounded-xl bg-predix-surface/60 border border-predix-border p-5 flex flex-col justify-between">
                  <div className="grid grid-cols-2 gap-4">
                    {/* File Name */}
                    <div className="col-span-2 pb-3 border-b border-predix-border/50">
                      <span className="label-mono text-[10px] text-predix-muted block mb-1">File Name</span>
                      <p className="text-xs font-mono text-white truncate" title={selectedFile?.name}>
                        {selectedFile?.name || '—'}
                      </p>
                    </div>

                    {/* File Size */}
                    <div>
                      <span className="label-mono text-[10px] text-predix-muted flex items-center gap-1 mb-1">
                        <HardDrive className="w-3 h-3" /> Size
                      </span>
                      <p className="text-sm font-mono font-semibold text-white">
                        {formatBytes(selectedFile?.size)}
                      </p>
                    </div>

                    {/* Format */}
                    <div>
                      <span className="label-mono text-[10px] text-predix-muted block mb-1">Format</span>
                      <p className="text-sm font-mono font-semibold text-predix-cyan uppercase">
                        {selectedFile?.name ? selectedFile.name.split('.').pop() : '—'}
                      </p>
                    </div>

                    {/* Duration */}
                    <div>
                      <span className="label-mono text-[10px] text-predix-muted flex items-center gap-1 mb-1">
                        <Clock className="w-3 h-3" /> Duration
                      </span>
                      <p className="text-sm font-mono font-semibold text-white">
                        {formatDuration(serverMetadata?.duration_seconds ?? videoDuration)}
                      </p>
                    </div>

                    {/* Resolution */}
                    <div>
                      <span className="label-mono text-[10px] text-predix-muted flex items-center gap-1 mb-1">
                        <Maximize2 className="w-3 h-3" /> Resolution
                      </span>
                      <p className="text-sm font-mono font-semibold text-white">
                        {serverMetadata
                          ? `${serverMetadata.width} × ${serverMetadata.height}`
                          : videoDimensions || 'Reading...'}
                      </p>
                    </div>

                    {serverMetadata && (
                      <>
                        <div>
                          <span className="label-mono text-[10px] text-predix-muted block mb-1">Frame Rate</span>
                          <p className="text-sm font-mono font-semibold text-white">
                            {serverMetadata.fps} FPS
                          </p>
                        </div>
                        <div>
                          <span className="label-mono text-[10px] text-predix-muted block mb-1">Frame Count</span>
                          <p className="text-sm font-mono font-semibold text-white">
                            {serverMetadata.frame_count.toLocaleString()}
                          </p>
                        </div>
                      </>
                    )}
                  </div>

                  {/* Backend Status / Staged Info */}
                  {backendResponse ? (
                    <div className="mt-4 pt-4 border-t border-predix-border/70 animate-fade-in">
                      <div className="flex items-center gap-2 mb-2">
                        <CheckCircle2 className="w-4 h-4 text-predix-emerald" />
                        <span className="text-xs font-semibold text-predix-emerald font-mono uppercase">
                          Stored on PREDIX Backend
                        </span>
                      </div>
                      <div className="space-y-1 font-mono text-[10px] text-predix-muted bg-predix-bg/60 p-2.5 rounded-lg border border-predix-border">
                        <div className="flex justify-between">
                          <span>Video ID:</span>
                          <span className="text-white truncate max-w-[170px]" title={backendResponse.video_id}>
                            {backendResponse.video_id}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span>Stored As:</span>
                          <span className="text-white truncate max-w-[170px]" title={backendResponse.stored_filename}>
                            {backendResponse.stored_filename}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span>Stored Bytes:</span>
                          <span className="text-white">{formatBytes(backendResponse.size_bytes)}</span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="mt-4 pt-4 border-t border-predix-border/50 text-[11px] font-mono text-predix-muted/80">
                      Staging preview ready. Click Upload to transfer to PREDIX backend.
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Upload Progress Bar (shown when UPLOADING or UPLOADED) */}
            {(uploadState === UPLOAD_STATES.UPLOADING || uploadState === UPLOAD_STATES.UPLOADED) && (
              <div className="p-4 rounded-xl bg-predix-surface border border-predix-border animate-fade-in">
                <div className="flex items-center justify-between text-xs font-mono mb-2">
                  <span className="text-white flex items-center gap-2">
                    {uploadState === UPLOAD_STATES.UPLOADING ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin text-predix-cyan" />
                        Uploading to PREDIX server...
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="w-3.5 h-3.5 text-predix-emerald" />
                        Upload Complete &amp; Verified
                      </>
                    )}
                  </span>
                  <span className="text-predix-cyan font-semibold">
                    {uploadProgress}% ({formatBytes(uploadedBytes)} / {formatBytes(selectedFile?.size)})
                  </span>
                </div>
                <div className="w-full h-2 rounded-full bg-predix-bg overflow-hidden border border-predix-border">
                  <div
                    className={`h-full transition-all duration-200 ${
                      uploadState === UPLOAD_STATES.UPLOADED ? 'bg-predix-emerald' : 'bg-predix-cyan'
                    }`}
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}

            {/* Action Bar */}
            <div className="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-predix-border">
              {/* Left: Remove / Reset */}
              <button
                type="button"
                id="reset-video-btn"
                onClick={handleResetOrRemove}
                disabled={uploadState === UPLOAD_STATES.UPLOADING || isDeleting}
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-predix-border bg-predix-surface hover:border-predix-red/40 hover:bg-predix-red/10 text-predix-muted hover:text-predix-red font-mono text-xs uppercase tracking-wider transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> Deleting Server Copy...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" /> Remove Video
                  </>
                )}
              </button>

              {/* Right: Select Another or Upload */}
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadState === UPLOAD_STATES.UPLOADING}
                  className="flex items-center gap-1.5 px-4 py-2.5 rounded-lg border border-predix-border bg-predix-surface hover:border-predix-cyan/40 text-predix-text font-mono text-xs uppercase tracking-wider transition-all disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <RefreshCw className="w-3.5 h-3.5 text-predix-cyan" /> Select Another
                </button>

                {uploadState !== UPLOAD_STATES.UPLOADED ? (
                  <button
                    type="button"
                    id="start-upload-btn"
                    onClick={handleUpload}
                    disabled={uploadState === UPLOAD_STATES.UPLOADING}
                    className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-predix-cyan text-predix-bg font-semibold text-xs uppercase tracking-wider hover:bg-predix-cyan/90 hover:shadow-cyan transition-all active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {uploadState === UPLOAD_STATES.UPLOADING ? (
                      <>
                        <Loader2 className="w-3.5 h-3.5 animate-spin" /> Uploading...
                      </>
                    ) : (
                      <>
                        <ArrowUpRight className="w-4 h-4" /> Upload to PREDIX
                      </>
                    )}
                  </button>
                ) : (
                  <div className="px-4 py-2 rounded-lg bg-predix-emerald/10 border border-predix-emerald/30 text-predix-emerald font-mono text-xs uppercase tracking-wider">
                    Video ready for analysis
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
