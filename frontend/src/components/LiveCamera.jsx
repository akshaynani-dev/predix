import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, CircleStop, Loader2, Radio, RotateCw, Trash2 } from 'lucide-react'
import { buildHlsSourceUrl, buildRtspStartMessage, getLiveCaptureSettings, liveStatusLabel, MAX_RECONNECTS, reconnectDelay } from '../liveProtocol'
import { formatForecastMetrics } from '../forecastMetrics'
import { fetchLiveAlertHistory, fetchLiveZoneHistory } from '../liveHistory'
import { occupancySparkline, occupancyTrendSummary } from '../occupancyTrend'
import { rankZoneReviewCues } from '../zoneReviewQueue'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const LIVE_SESSIONS_URL = (() => {
  const url = new URL(API_URL)
  url.pathname = `${url.pathname.replace(/\/$/, '')}/api/live/sessions`
  url.searchParams.set('limit', '5')
  return url.toString()
})()
const LIVE_URL = (() => {
  const url = new URL(API_URL)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `${url.pathname.replace(/\/$/, '')}/api/live/ws`
  return url.toString()
})()
const {
  frameWidth: TARGET_FRAME_WIDTH,
  frameHeight: TARGET_FRAME_HEIGHT,
  frameIntervalMs: MIN_FRAME_INTERVAL_MS,
} = getLiveCaptureSettings({
  frameWidth: import.meta.env.VITE_LIVE_FRAME_WIDTH,
  frameHeight: import.meta.env.VITE_LIVE_FRAME_HEIGHT,
  frameIntervalMs: import.meta.env.VITE_LIVE_FRAME_INTERVAL_MS,
})
const HLS_STALL_TIMEOUT_MS = 10000
export default function LiveCamera() {
  const videoRef = useRef(null)
  const canvasRef = useRef(null)
  const streamRef = useRef(null)
  const socketRef = useRef(null)
  const connectSocketRef = useRef(null)
  const frameLoopRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const hlsRetryTimerRef = useRef(null)
  const stopTimerRef = useRef(null)
  const sourceModeRef = useRef('browser_camera')
  const stoppedRef = useRef(true)
  const inFlightRef = useRef(false)
  const lastSentRef = useRef(0)
  const sentAtRef = useRef(0)
  const reconnectCountRef = useRef(0)
  const hlsRetryCountRef = useRef(0)
  const hlsRecoveringRef = useRef(false)
  const hlsProgressRef = useRef({ currentTime: 0, observedAt: 0 })
  const hlsUrlRef = useRef('')
  const hlsFailureRef = useRef(null)
  const hlsCanvasFailureRef = useRef(null)
  const previousStatusRef = useRef('idle')
  const [status, setStatus] = useState('idle')
  const [inputMode, setInputMode] = useState('browser_camera')
  const [rtspUrl, setRtspUrl] = useState('')
  const [hlsUrl, setHlsUrl] = useState('')
  const [nativeHlsSupported, setNativeHlsSupported] = useState(false)
  const [rtspPreview, setRtspPreview] = useState(null)
  const [error, setError] = useState(null)
  const [metrics, setMetrics] = useState(null)
  const [detections, setDetections] = useState([])
  const [frameSize, setFrameSize] = useState({ width: 640, height: 360 })
  const [reconnectCount, setReconnectCount] = useState(0)
  const [recentSessions, setRecentSessions] = useState([])
  const [historyError, setHistoryError] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)
  const historyRequestRef = useRef(null)
  const alertHistoryRequestRef = useRef(null)
  const [selectedZoneHistory, setSelectedZoneHistory] = useState(null)
  const [zoneHistoryLoading, setZoneHistoryLoading] = useState(false)
  const [zoneHistoryError, setZoneHistoryError] = useState(null)
  const zoneHistoryRequestRef = useRef(null)
  const [selectedAlertHistory, setSelectedAlertHistory] = useState(null)
  const [alertHistoryLoading, setAlertHistoryLoading] = useState(false)
  const [alertHistoryError, setAlertHistoryError] = useState(null)
  const zonesRef = useRef([])
  const [zones, setZones] = useState([])
  const [zoneTrends, setZoneTrends] = useState({})
  const [zoneName, setZoneName] = useState('Entrance')
  const [zoneCapacity, setZoneCapacity] = useState('')
  const [draftPolygon, setDraftPolygon] = useState([])
  const [isDrawing, setIsDrawing] = useState(false)

  useEffect(() => {
    const video = videoRef.current
    setNativeHlsSupported(Boolean(
      video?.canPlayType('application/vnd.apple.mpegurl')
      || video?.canPlayType('application/x-mpegURL'),
    ))
  }, [])

  const loadRecentSessions = useCallback(async (signal) => {
    const controller = signal ? null : new AbortController()
    const requestSignal = signal || controller.signal
    if (controller) historyRequestRef.current = controller
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const response = await fetch(LIVE_SESSIONS_URL, { signal: requestSignal })
      if (!response.ok) throw new Error(`History request failed (${response.status}).`)
      const payload = await response.json()
      setRecentSessions(payload.sessions || [])
    } catch (requestError) {
      if (!requestSignal.aborted && requestError.name !== 'AbortError') setHistoryError('Live session history is unavailable.')
    } finally {
      if (!requestSignal.aborted) setHistoryLoading(false)
      if (controller && historyRequestRef.current === controller) historyRequestRef.current = null
    }
  }, [])

  useEffect(() => {
    historyRequestRef.current?.abort()
    const previousStatus = previousStatusRef.current
    previousStatusRef.current = status
    if (!['idle', 'offline', 'error'].includes(status)) {
      return () => historyRequestRef.current?.abort()
    }
    const controller = new AbortController()
    historyRequestRef.current = controller
    const delay = ['live', 'reconnecting'].includes(previousStatus) ? 300 : 0
    const timer = setTimeout(() => loadRecentSessions(controller.signal), delay)
    return () => {
      clearTimeout(timer)
      controller.abort()
      if (historyRequestRef.current === controller) historyRequestRef.current = null
    }
  }, [loadRecentSessions, status])

  useEffect(() => () => {
    zoneHistoryRequestRef.current?.abort()
    alertHistoryRequestRef.current?.abort()
  }, [])

  const loadZoneHistory = useCallback(async (sessionId, zoneId, zoneName) => {
    zoneHistoryRequestRef.current?.abort()
    const controller = new AbortController()
    zoneHistoryRequestRef.current = controller
    setSelectedZoneHistory({ sessionId, zoneId, zoneName, observations: [], predictions: [] })
    setZoneHistoryLoading(true)
    setZoneHistoryError(null)
    try {
      const payload = await fetchLiveZoneHistory({
        apiUrl: API_URL, sessionId, zoneId, signal: controller.signal,
      })
      if (!controller.signal.aborted) setSelectedZoneHistory({ ...payload, zoneName })
    } catch (requestError) {
      if (!controller.signal.aborted && requestError.name !== 'AbortError') {
        setZoneHistoryError('Stored occupancy history could not be loaded.')
      }
    } finally {
      if (!controller.signal.aborted) setZoneHistoryLoading(false)
      if (zoneHistoryRequestRef.current === controller) zoneHistoryRequestRef.current = null
    }
  }, [])

  const loadAlertHistory = useCallback(async (sessionId) => {
    alertHistoryRequestRef.current?.abort()
    const controller = new AbortController()
    alertHistoryRequestRef.current = controller
    setSelectedAlertHistory({ sessionId, alerts: [] })
    setAlertHistoryLoading(true)
    setAlertHistoryError(null)
    try {
      const payload = await fetchLiveAlertHistory({ apiUrl: API_URL, sessionId, signal: controller.signal })
      if (!controller.signal.aborted) setSelectedAlertHistory(payload)
    } catch (requestError) {
      if (!controller.signal.aborted && requestError.name !== 'AbortError') {
        setAlertHistoryError('Stored occupancy-alert history could not be loaded.')
      }
    } finally {
      if (!controller.signal.aborted) setAlertHistoryLoading(false)
      if (alertHistoryRequestRef.current === controller) alertHistoryRequestRef.current = null
    }
  }, [])

  const syncZones = useCallback((nextZones) => {
    zonesRef.current = nextZones
    setZones(nextZones)
    setZoneTrends({})
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: 'configure_zones', zones: nextZones }))
    }
  }, [])

  const addPolygonPoint = (event) => {
    if (!isDrawing) return
    const rect = event.currentTarget.getBoundingClientRect()
    setDraftPolygon((points) => [...points, [
      Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    ]])
  }

  const saveZone = () => {
    if (draftPolygon.length < 3 || !zoneName.trim()) return
    const base = zoneName.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-|-$/g, '').slice(0, 56) || 'zone'
    const zoneId = `${base}-${Date.now().toString(36)}`
    const zone = {
      zone_id: zoneId,
      name: zoneName.trim(),
      polygon: draftPolygon,
      ...(zoneCapacity ? { occupancy_capacity: Number(zoneCapacity) } : {}),
    }
    syncZones([...zonesRef.current, zone])
    setDraftPolygon([])
    setIsDrawing(false)
  }

  const releaseCamera = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => {
        track.onended = null
        track.stop()
      })
      streamRef.current = null
    }
    if (videoRef.current) {
      videoRef.current.pause()
      videoRef.current.srcObject = null
      videoRef.current.onplaying = null
      videoRef.current.onerror = null
      videoRef.current.removeAttribute('src')
      videoRef.current.load()
    }
  }, [])

  const stopLive = useCallback(() => {
    stoppedRef.current = true
    if (frameLoopRef.current) cancelAnimationFrame(frameLoopRef.current)
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    if (hlsRetryTimerRef.current) clearTimeout(hlsRetryTimerRef.current)
    if (stopTimerRef.current) clearTimeout(stopTimerRef.current)
    frameLoopRef.current = null
    reconnectTimerRef.current = null
    inFlightRef.current = false
    hlsRecoveringRef.current = false
    hlsFailureRef.current = null
    hlsCanvasFailureRef.current = null
    const socket = socketRef.current
    socketRef.current = null
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'stop' }))
      stopTimerRef.current = setTimeout(() => socket.close(1000, 'Operator stopped live video'), 250)
    } else if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, 'Operator stopped live video')
    }
    releaseCamera()
    setDetections([])
    setMetrics(null)
    setZoneTrends({})
    setRtspPreview(null)
    setRtspUrl('')
    setHlsUrl('')
    hlsUrlRef.current = ''
    setStatus('idle')
  }, [releaseCamera])

  const startFrameLoop = useCallback(() => {
    if (frameLoopRef.current) return
    const pump = (now) => {
      if (stoppedRef.current) {
        frameLoopRef.current = null
        return
      }
      const socket = socketRef.current
      const video = videoRef.current
      if (sourceModeRef.current === 'hls' && video && !hlsRecoveringRef.current) {
        if (video.currentTime > hlsProgressRef.current.currentTime + 0.01) {
          hlsProgressRef.current = { currentTime: video.currentTime, observedAt: now }
        } else if (now - hlsProgressRef.current.observedAt > HLS_STALL_TIMEOUT_MS) {
          hlsFailureRef.current?.()
        }
      }
      if (socket?.readyState === WebSocket.OPEN && !inFlightRef.current && now - lastSentRef.current >= MIN_FRAME_INTERVAL_MS) {
        if (sourceModeRef.current === 'rtsp') {
          inFlightRef.current = true
          sentAtRef.current = performance.now()
          lastSentRef.current = now
          socket.send(JSON.stringify({ type: 'next_frame' }))
        } else if (video?.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !hlsRecoveringRef.current) {
          const width = video.videoWidth || TARGET_FRAME_WIDTH
          const height = video.videoHeight || Math.round(TARGET_FRAME_WIDTH * 9 / 16)
          const scale = Math.min(1, TARGET_FRAME_WIDTH / width, TARGET_FRAME_HEIGHT / height)
          const frameWidth = Math.max(1, Math.round(width * scale))
          const frameHeight = Math.max(1, Math.round(height * scale))
          const canvas = canvasRef.current
          canvas.width = frameWidth
          canvas.height = frameHeight
          try {
            canvas.getContext('2d')?.drawImage(video, 0, 0, frameWidth, frameHeight)
            canvas.toBlob((blob) => {
              if (!blob) {
                if (sourceModeRef.current === 'hls') hlsCanvasFailureRef.current?.()
                return
              }
              if (stoppedRef.current || socket.readyState !== WebSocket.OPEN) return
              inFlightRef.current = true
              sentAtRef.current = performance.now()
              lastSentRef.current = now
              socket.send(blob)
            }, 'image/jpeg', 0.76)
          } catch {
            if (sourceModeRef.current === 'hls') hlsCanvasFailureRef.current?.()
          }
        }
      }
      frameLoopRef.current = requestAnimationFrame(pump)
    }
    frameLoopRef.current = requestAnimationFrame(pump)
  }, [])

  const connectSocket = useCallback((attempt = 0, mode = 'browser_camera', sourceMessage = null) => {
    if (stoppedRef.current) return
    sourceModeRef.current = mode
    setStatus(attempt ? 'reconnecting' : 'connecting')
    const socket = new WebSocket(LIVE_URL)
    socketRef.current = socket

    socket.onopen = () => {
      if (stoppedRef.current) {
        socket.close()
        return
      }
      if (zonesRef.current.length) socket.send(JSON.stringify({ type: 'configure_zones', zones: zonesRef.current }))
      setError(null)
      if (mode === 'rtsp') {
        socket.send(sourceMessage)
      } else if (mode === 'hls') {
        socket.send(JSON.stringify({ type: 'select_browser_source', source_kind: 'hls' }))
      } else {
        setStatus('live')
        startFrameLoop()
      }
    }

    socket.onmessage = (event) => {
      let message
      try {
        message = JSON.parse(event.data)
      } catch {
        setError('The live analysis service returned an unreadable response.')
        return
      }
      if (message.type === 'rejected') {
        stoppedRef.current = true
        releaseCamera()
        setStatus('error')
        setError(message.detail)
        socket.close()
        return
      }
      if (message.type === 'error') {
        inFlightRef.current = false
        setError(message.detail)
        return
      }
      if (message.type === 'source_error') {
        stoppedRef.current = true
        if (mode === 'hls') releaseCamera()
        setStatus('error')
        setError(message.detail || 'The RTSP source could not be opened.')
        if (mode === 'hls') setHlsUrl('')
        else setRtspUrl('')
        socket.close()
        return
      }
      if (message.type === 'source_ready') {
        setError(null)
        setStatus('live')
        startFrameLoop()
        return
      }
      if (message.type === 'session_stopped') {
        if (stopTimerRef.current) clearTimeout(stopTimerRef.current)
        socket.close(1000, 'Operator stopped live video')
        return
      }
      if (message.type === 'stream_disconnected') {
        setError('RTSP stream disconnected. PREDIX will try a bounded reconnect.')
        setStatus('reconnecting')
        inFlightRef.current = false
        return
      }
      if (message.type === 'zones_configured') return
      if (message.type === 'zone_config_error') {
        setError(message.detail)
        return
      }
      if (message.type !== 'observation') return

      inFlightRef.current = false
      setFrameSize({ width: message.frame_width, height: message.frame_height })
      setDetections(message.detections || [])
      setMetrics({
        ...message,
        roundTripLatencyMs: Math.round(performance.now() - sentAtRef.current),
      })
      if (Number.isFinite(message.session_elapsed_seconds)) {
        setZoneTrends((previous) => {
          const next = { ...previous }
          for (const zone of message.zone_occupancy || []) {
            next[zone.zone_id] = [
              ...(previous[zone.zone_id] || []),
              { elapsed_seconds: message.session_elapsed_seconds, count: zone.current_estimate },
            ].slice(-60)
          }
          return next
        })
      }
      setRtspPreview(message.source_kind === 'rtsp' && message.preview_jpeg
        ? `data:image/jpeg;base64,${message.preview_jpeg}`
        : null)
      setStatus('live')
    }

    socket.onerror = () => socket.close()
    socket.onclose = () => {
      if (socketRef.current === socket) socketRef.current = null
      inFlightRef.current = false
      if (stoppedRef.current) return
      if (reconnectCountRef.current < MAX_RECONNECTS) {
        const retry = reconnectCountRef.current
        reconnectCountRef.current += 1
        setReconnectCount(reconnectCountRef.current)
        setStatus('reconnecting')
        reconnectTimerRef.current = setTimeout(
          () => connectSocketRef.current?.(retry + 1, mode, sourceMessage),
          reconnectDelay(retry),
        )
      } else {
        stoppedRef.current = true
        setStatus('offline')
        const sourceName = mode === 'rtsp' ? 'RTSP source' : mode === 'hls' ? 'HLS stream' : 'camera'
        setError(`STREAM DISCONNECTED. Reconnection attempts ended; stop and start the ${sourceName} to retry.`)
        releaseCamera()
        if (mode === 'rtsp') setRtspUrl('')
        if (mode === 'hls') setHlsUrl('')
      }
    }
  }, [releaseCamera, startFrameLoop])
  useEffect(() => {
    connectSocketRef.current = connectSocket
  }, [connectSocket])

  const startLive = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('error')
      setError('This browser does not provide camera access. Open PREDIX on localhost or HTTPS.')
      return
    }
    setError(null)
    setRtspPreview(null)
    setZoneTrends({})
    sourceModeRef.current = 'browser_camera'
    setStatus('connecting')
    stoppedRef.current = false
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: TARGET_FRAME_WIDTH },
          height: { ideal: TARGET_FRAME_HEIGHT },
          frameRate: { ideal: 10, max: 15 },
        },
      })
      if (stoppedRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      streamRef.current = stream
      const video = videoRef.current
      video.srcObject = stream
      await video.play()
      stream.getVideoTracks().forEach((track) => {
        track.onended = () => {
          if (stoppedRef.current) return
          stoppedRef.current = true
          socketRef.current?.close()
          releaseCamera()
          setStatus('offline')
          setError('Camera disconnected. Start the live camera again when it is available.')
        }
      })
      reconnectCountRef.current = 0
      setReconnectCount(0)
      connectSocket()
    } catch (cameraError) {
      if (stoppedRef.current) return
      stoppedRef.current = true
      releaseCamera()
      setStatus('error')
      setError(cameraError.name === 'NotAllowedError'
        ? 'Camera permission was denied. Allow camera access in your browser to start live analysis.'
        : 'PREDIX could not open the selected camera.')
    }
  }, [connectSocket, releaseCamera])

  const startRtsp = useCallback(() => {
    const sourceMessage = buildRtspStartMessage(rtspUrl)
    if (!sourceMessage) {
      setStatus('error')
      setError('Enter a valid rtsp:// or rtsps:// camera URL.')
      return
    }
    stoppedRef.current = false
    sourceModeRef.current = 'rtsp'
    reconnectCountRef.current = 0
    setReconnectCount(0)
    setError(null)
    setMetrics(null)
    setDetections([])
    setZoneTrends({})
    setRtspPreview(null)
    setStatus('connecting')
    connectSocket(0, 'rtsp', sourceMessage)
  }, [connectSocket, rtspUrl])

  const startHls = useCallback(async () => {
    const sourceUrl = buildHlsSourceUrl(hlsUrl)
    if (!sourceUrl) {
      setStatus('error')
      setError('Enter an HTTPS HLS playlist URL ending in .m3u8. URLs containing credentials or fragments are not accepted.')
      return
    }
    if (!nativeHlsSupported) {
      setStatus('error')
      setError('This browser does not report native HLS playback support. Open PREDIX in Safari or use a browser with built-in HLS playback.')
      return
    }

    const video = videoRef.current
    if (!video) return
    stoppedRef.current = false
    sourceModeRef.current = 'hls'
    hlsUrlRef.current = sourceUrl
    hlsRetryCountRef.current = 0
    hlsRecoveringRef.current = false
    hlsProgressRef.current = { currentTime: 0, observedAt: performance.now() }
    reconnectCountRef.current = 0
    setReconnectCount(0)
    setError(null)
    setMetrics(null)
    setDetections([])
    setZoneTrends({})
    setRtspPreview(null)
    setStatus('connecting')

    const retryPlayback = () => {
      if (stoppedRef.current || hlsRecoveringRef.current) return
      hlsRecoveringRef.current = true
      if (hlsRetryCountRef.current >= MAX_RECONNECTS) {
        stoppedRef.current = true
        if (frameLoopRef.current) cancelAnimationFrame(frameLoopRef.current)
        if (hlsRetryTimerRef.current) clearTimeout(hlsRetryTimerRef.current)
        frameLoopRef.current = null
        hlsRetryTimerRef.current = null
        socketRef.current?.close(1000, 'HLS playback retries exhausted')
        releaseCamera()
        setHlsUrl('')
        hlsUrlRef.current = ''
        setStatus('offline')
        setError('STREAM DISCONNECTED. HLS playback retries ended; confirm the HTTPS playlist and CORS access, then restart the stream.')
        return
      }
      const retry = hlsRetryCountRef.current
      hlsRetryCountRef.current += 1
      setStatus('reconnecting')
      setError('HLS playback stalled or disconnected. Retrying with bounded backoff.')
      hlsRetryTimerRef.current = setTimeout(async () => {
        hlsRetryTimerRef.current = null
        if (stoppedRef.current || !videoRef.current) return
        const currentVideo = videoRef.current
        currentVideo.src = hlsUrlRef.current
        currentVideo.load()
        try {
          await currentVideo.play()
          hlsProgressRef.current = { currentTime: currentVideo.currentTime, observedAt: performance.now() }
          hlsRecoveringRef.current = false
          setError(null)
          if (socketRef.current?.readyState === WebSocket.OPEN) setStatus('live')
        } catch {
          hlsRecoveringRef.current = false
          retryPlayback()
        }
      }, reconnectDelay(retry))
    }
    hlsCanvasFailureRef.current = () => {
      if (stoppedRef.current) return
      stoppedRef.current = true
      if (frameLoopRef.current) cancelAnimationFrame(frameLoopRef.current)
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (hlsRetryTimerRef.current) clearTimeout(hlsRetryTimerRef.current)
      frameLoopRef.current = null
      reconnectTimerRef.current = null
      hlsRetryTimerRef.current = null
      socketRef.current?.close(1000, 'HLS frame sampling blocked by CORS')
      releaseCamera()
      setStatus('error')
      setError('The browser could play this HLS stream but could not read frames for analysis. Enable anonymous CORS access on the HLS host and restart the stream.')
    }
    hlsFailureRef.current = retryPlayback
    video.crossOrigin = 'anonymous'
    video.onplaying = () => {
      hlsProgressRef.current = { currentTime: video.currentTime, observedAt: performance.now() }
      hlsRecoveringRef.current = false
      setError(null)
      if (socketRef.current?.readyState === WebSocket.OPEN) setStatus('live')
    }
    video.onerror = retryPlayback
    video.src = sourceUrl
    video.load()
    try {
      await video.play()
      connectSocket(0, 'hls')
    } catch {
      retryPlayback()
    }
  }, [connectSocket, hlsUrl, nativeHlsSupported, releaseCamera])

  useEffect(() => () => stopLive(), [stopLive])

  const aspectRatio = `${frameSize.width} / ${frameSize.height}`
  const isInactive = ['idle', 'offline', 'error'].includes(status)
  const zoneReviewCues = rankZoneReviewCues(metrics?.zone_occupancy)

  return (
    <section aria-label="Live camera input" className="glass-card p-4 sm:p-6 space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-predix-cyan/20 bg-predix-cyan/10 text-predix-cyan">
            <Camera className="h-5 w-5" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white">Live camera</h2>
            <p className="text-xs text-predix-muted">Browser camera, native HLS playback, and configured RTSP frames use the shared PREDIX analysis pipeline.</p>
          </div>
        </div>
        <div className={`flex items-center gap-2 self-start rounded-full border px-3 py-1.5 font-mono text-[10px] ${status === 'live' ? 'border-predix-red/40 bg-predix-red/10 text-predix-red' : 'border-predix-border bg-predix-surface text-predix-muted'}`} aria-live="polite">
          <span className={`h-2 w-2 rounded-full ${status === 'live' ? 'animate-pulse bg-predix-red' : status === 'connecting' || status === 'reconnecting' ? 'animate-pulse bg-predix-amber' : 'bg-predix-muted'}`} />
          {liveStatusLabel(status)}
        </div>
      </div>

      {error && <p role="alert" className="rounded-lg border border-predix-red/30 bg-predix-red/5 p-3 text-xs text-predix-red">{error}</p>}

      <div className="space-y-3 rounded-lg border border-predix-border bg-predix-surface/40 p-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Live video source">
          <button type="button" disabled={!isInactive} onClick={() => setInputMode('browser_camera')} aria-pressed={inputMode === 'browser_camera'} className={`rounded border px-3 py-2 text-xs ${inputMode === 'browser_camera' ? 'border-predix-cyan text-predix-cyan' : 'border-predix-border text-predix-muted'} disabled:opacity-50`}>Browser camera</button>
          <button type="button" disabled={!isInactive} onClick={() => setInputMode('rtsp')} aria-pressed={inputMode === 'rtsp'} className={`rounded border px-3 py-2 text-xs ${inputMode === 'rtsp' ? 'border-predix-cyan text-predix-cyan' : 'border-predix-border text-predix-muted'} disabled:opacity-50`}>RTSP camera</button>
          <button type="button" disabled={!isInactive || !nativeHlsSupported} onClick={() => setInputMode('hls')} aria-pressed={inputMode === 'hls'} className={`rounded border px-3 py-2 text-xs ${inputMode === 'hls' ? 'border-predix-cyan text-predix-cyan' : 'border-predix-border text-predix-muted'} disabled:opacity-50`}>HLS stream</button>
        </div>
        {!nativeHlsSupported && <p className="text-[10px] text-predix-amber">HLS input is disabled because this browser does not advertise native HLS playback. Try Safari on macOS/iOS.</p>}
        {inputMode === 'rtsp' && (
          <div className="space-y-2">
            <label className="block text-xs text-predix-muted">RTSP camera URL
              <input type="text" inputMode="url" autoComplete="off" spellCheck="false" value={rtspUrl} onChange={(event) => setRtspUrl(event.target.value)} disabled={!isInactive} placeholder="rtsp://camera-host:554/stream" className="mt-1 w-full rounded border border-predix-border bg-predix-bg px-3 py-2 font-mono text-xs text-white placeholder:text-predix-muted/60 disabled:opacity-50" />
            </label>
            <p className="text-[10px] text-predix-muted">The RTSP hostname must be in the backend `RTSP_ALLOWED_HOSTS` setting. If the camera requires credentials, include them in the URL. PREDIX sends it to the backend for this session and does not save it in session history. Use only on a trusted network; PREDIX does not authenticate users.</p>
          </div>
        )}
        {inputMode === 'hls' && (
          <div className="space-y-2">
            <label className="block text-xs text-predix-muted">HTTPS HLS playlist URL
              <input type="url" inputMode="url" autoComplete="off" spellCheck="false" value={hlsUrl} onChange={(event) => setHlsUrl(event.target.value)} disabled={!isInactive} placeholder="https://camera.example/live/index.m3u8" className="mt-1 w-full rounded border border-predix-border bg-predix-bg px-3 py-2 font-mono text-xs text-white placeholder:text-predix-muted/60 disabled:opacity-50" />
            </label>
            <p className="text-[10px] text-predix-muted">HLS plays directly in this browser; PREDIX samples frames from the video element and sends only those frames to its shared analysis WebSocket. The browser must support native HLS, and the stream host must allow anonymous CORS so the preview can be analyzed. Use an HTTPS .m3u8 URL without embedded credentials. The URL stays in this page's memory and is not saved in session history.</p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(260px,1fr)]">
        <div className="space-y-3">
          <div className="relative mx-auto w-full overflow-hidden rounded-xl border border-predix-border bg-black" style={{ aspectRatio }}>
            {inputMode === 'rtsp' && rtspPreview
              ? <img src={rtspPreview} className="absolute inset-0 h-full w-full object-contain" alt="Sampled RTSP camera frame" />
              : <video ref={videoRef} autoPlay muted playsInline crossOrigin="anonymous" className={`absolute inset-0 h-full w-full object-contain ${inputMode === 'rtsp' ? 'hidden' : ''}`} aria-label="Live camera preview" />}
            {status === 'live' && metrics && (
              <svg onClick={addPolygonPoint} className={`absolute inset-0 h-full w-full ${isDrawing ? 'cursor-crosshair' : 'pointer-events-none'}`} preserveAspectRatio="none" viewBox={`0 0 ${frameSize.width} ${frameSize.height}`} role="img" aria-label="Live detections and configured zones">
                {zones.map((zone) => (
                  <g key={zone.zone_id}>
                    <polygon points={zone.polygon.map(([x, y]) => `${x * frameSize.width},${y * frameSize.height}`).join(' ')} fill="#58e1ee" fillOpacity="0.12" stroke="#58e1ee" strokeWidth="2" />
                    <text x={zone.polygon[0][0] * frameSize.width} y={Math.max(14, zone.polygon[0][1] * frameSize.height - 4)} fill="#07131b" fontSize="13" fontWeight="700" paintOrder="stroke" stroke="#58e1ee" strokeWidth="4">{zone.name}</text>
                  </g>
                ))}
                {draftPolygon.length > 0 && <>
                  <polyline points={draftPolygon.map(([x, y]) => `${x * frameSize.width},${y * frameSize.height}`).join(' ')} fill="none" stroke="#f5bc54" strokeWidth="2" />
                  {draftPolygon.map(([x, y], i) => <circle key={i} cx={x * frameSize.width} cy={y * frameSize.height} r="5" fill="#f5bc54" />)}
                </>}
                {detections.map((detection, index) => {
                  const { x1, y1, x2, y2 } = detection.bbox
                  return (
                    <g key={`${detection.class}-${index}`}>
                      <title>{`Temporary anonymous track ${detection.track_id}; dwell ${Number(detection.dwell_seconds || 0).toFixed(1)} seconds${detection.direction ? `; image movement dx ${detection.direction.dx_pixels} px, dy ${detection.direction.dy_pixels} px` : ''}`}</title>
                      <rect x={x1} y={y1} width={Math.max(0, x2 - x1)} height={Math.max(0, y2 - y1)} fill="none" stroke="#58e1ee" strokeWidth="2" />
                      <text x={x1} y={Math.max(12, y1 - 4)} fill="#07131b" fontSize="12" fontWeight="700" paintOrder="stroke" stroke="#58e1ee" strokeWidth="4">
                        {detection.class.toUpperCase()} {detection.confidence.toFixed(2)} CONFIDENCE
                      </text>
                      <text x={x1} y={Math.min(frameSize.height - 3, y2 + 14)} fill="#07131b" fontSize="10" fontWeight="700" paintOrder="stroke" stroke="#58e1ee" strokeWidth="3">
                        TRACK {detection.track_id} · DWELL {Number(detection.dwell_seconds || 0).toFixed(1)}s
                      </text>
                    </g>
                  )
                })}
              </svg>
            )}
            {status !== 'live' && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/50 text-center">
                {status === 'connecting' || status === 'reconnecting'
                  ? <Loader2 className="h-7 w-7 animate-spin text-predix-cyan" />
                  : <Radio className="h-7 w-7 text-predix-muted" />}
                <span className="font-mono text-xs text-white">{liveStatusLabel(status)}</span>
              </div>
            )}
          </div>
          <canvas ref={canvasRef} className="hidden" aria-hidden="true" />
          <p className="text-[10px] leading-relaxed text-predix-muted">Camera permission is requested only after you start the live camera. PREDIX stops the camera tracks when you stop this session or leave this view.</p>
          <div className="rounded-lg border border-predix-border bg-predix-surface/40 p-3 space-y-2 text-xs">
            <div className="flex items-center justify-between"><p className="font-semibold text-white">Live zones</p><button type="button" onClick={() => { setDraftPolygon([]); setIsDrawing(true) }} disabled={isDrawing} className="rounded border border-predix-cyan/40 px-2 py-1 text-predix-cyan disabled:opacity-50">Draw zone</button></div>
            {isDrawing && <p className="text-predix-muted">Click at least three points in the preview to outline a zone.</p>}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_120px]">
              <label className="text-predix-muted">Zone name<input value={zoneName} onChange={(event) => setZoneName(event.target.value)} maxLength={100} className="mt-1 w-full rounded border border-predix-border bg-predix-bg px-2 py-1 text-white" /></label>
              <label className="text-predix-muted">Capacity (optional)<input type="number" min="1" max="100000" value={zoneCapacity} onChange={(event) => setZoneCapacity(event.target.value)} className="mt-1 w-full rounded border border-predix-border bg-predix-bg px-2 py-1 text-white" /></label>
            </div>
            {isDrawing && <div className="flex gap-2"><button type="button" onClick={saveZone} disabled={draftPolygon.length < 3 || !zoneName.trim()} className="rounded bg-predix-cyan px-2 py-1 font-semibold text-predix-bg disabled:opacity-50">Save polygon ({draftPolygon.length} points)</button><button type="button" onClick={() => { setDraftPolygon([]); setIsDrawing(false) }} className="rounded border border-predix-border px-2 py-1 text-white">Cancel</button></div>}
            <p className="text-[10px] leading-relaxed text-predix-muted">Live occupancy and capacity status use detected anonymous tracks. Missed detections and occlusion can undercount, especially in dense scenes; the estimate is not a verified headcount or safety finding.</p>
            {zones.map((zone) => {
              const liveZone = metrics?.zone_occupancy?.find((item) => item.zone_id === zone.zone_id)
              const minuteForecast = liveZone?.occupancy_forecast?.forecasts?.find((item) => item.horizon_seconds === 60)
              return (
                <div key={zone.zone_id} className="border-t border-predix-border pt-2 text-predix-muted">
                  <div className="flex items-center justify-between">
                    <span><span className="text-white">{zone.name}</span>{liveZone ? ` · ${liveZone.current_estimate} estimated active tracks · ${liveZone.capacity_status}${liveZone.temporally_carried_track_count ? ` · ${liveZone.temporally_carried_track_count} briefly carried` : ''}${liveZone.trend_change ? ` · trend ${liveZone.trend_change > 0 ? '+' : ''}${liveZone.trend_change}` : ''} · entries ${liveZone.observed_entries} · exits ${liveZone.observed_exits}` : ' · awaiting live frames'}</span>
                    <button type="button" aria-label={`Remove ${zone.name}`} onClick={() => syncZones(zonesRef.current.filter((item) => item.zone_id !== zone.zone_id))} className="p-1 text-predix-muted hover:text-predix-red"><Trash2 className="h-3.5 w-3.5" /></button>
                  </div>
                  {liveZone && (
                  <div className="mt-1 text-[10px]">
                      <p className="mt-2 text-predix-muted">Recent occupancy samples</p>
                      <svg viewBox="0 0 240 42" role="img" aria-label={`${zone.name} occupancy trend: ${occupancyTrendSummary(zoneTrends[zone.zone_id] || [])}`} className="mt-1 h-10 w-full rounded bg-predix-bg/70">
                        <polyline points={occupancySparkline(zoneTrends[zone.zone_id] || [])} fill="none" stroke="#58e1ee" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
                      </svg>
                      <p>{occupancyTrendSummary(zoneTrends[zone.zone_id] || [])} Last {zoneTrends[zone.zone_id]?.length || 0} sampled estimates, session-relative time.</p>
                      <p>Occupancy deviation: {liveZone.occupancy_anomaly?.status?.replaceAll('_', ' ').toUpperCase() || 'INSUFFICIENT DATA'}</p>
                      <p className="mt-1 font-semibold text-predix-cyan">Security attention: {liveZone.security_attention?.status?.replaceAll('_', ' ').toUpperCase() || 'UNAVAILABLE'}</p>
                      {liveZone.security_attention?.recommendation && <p className="mt-1 text-predix-text">{liveZone.security_attention.recommendation}</p>}
                      {liveZone.security_attention?.signals?.map((signal) => <p key={signal.signal} className="mt-1">Evidence: {signal.signal.replaceAll('_', ' ')}{signal.status ? ` · ${signal.status}` : ''}{signal.evidence ? ` · ${signal.evidence}` : ''}</p>)}
                      <p className="mt-1">Human review guidance only; not validated as an incident predictor and does not allocate security resources.</p>
                      <p>Next-minute mean occupancy estimate: {minuteForecast?.status === 'available'
                        ? `${minuteForecast.forecast} ± ${minuteForecast.uncertainty.mae} estimated visible people`
                        : 'insufficient continuous history for validated prediction'}
                      </p>
                      {minuteForecast?.status === 'available' && <p>{minuteForecast.model} · {minuteForecast.evaluation.validation_windows} rolling validation windows · {formatForecastMetrics(minuteForecast.evaluation.selected_model)}</p>}
                      {minuteForecast?.status === 'available' && <p>As of live session {Number(liveZone.occupancy_forecast.as_of_session_seconds).toFixed(0)}s · based on {minuteForecast.supporting_observations} completed 15-second occupancy buckets.</p>}
                      <p className="mt-1">Uses completed 15-second buckets; requires six continuous minutes for this horizon. The uncertainty is validation MAE, not a calibrated probability or guarantee.</p>
                    </div>
                  )}
                </div>
              )
            })}
            {zones.length === 0 && !isDrawing && <p className="text-predix-muted">No zone configured. Draw a polygon to see live zone occupancy.</p>}
            <p className="text-[10px] text-predix-muted">Zone settings and per-track membership stay in memory for this session; aggregate frame, detection, and zone totals are retained in live-session history until deleted. Counts are estimates from sampled detections, not unique-person counts; transitions require the same anonymous track to continue across frames.</p>
          </div>
        </div>

        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {[
              ['Sampled input FPS', metrics?.source_fps ?? '—'],
              ['Inference FPS', metrics?.inference_fps ?? '—'],
              ['Round-trip latency', metrics ? `${metrics.roundTripLatencyMs} ms` : '—'],
              ['Raw detections / frame', metrics?.detection_count ?? '—'],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-predix-border bg-predix-surface/50 p-3">
                <p className="label-mono text-[9px] text-predix-muted">{label}</p>
                <p className="mt-1 font-mono text-lg font-semibold text-white">{value}</p>
              </div>
            ))}
          </div>
          <div className="rounded-lg border border-predix-border bg-predix-surface/40 p-3 text-xs">
            <p className="font-semibold text-white">Crowd estimate</p>
            {metrics?.occupancy ? (
              <>
                <p className="mt-1 text-2xl font-semibold text-predix-cyan">{metrics.occupancy.count} <span className="text-xs font-normal text-predix-muted">estimated active person tracks</span></p>
                <p className="mt-1 text-predix-muted">{metrics.occupancy.raw_person_detection_instances ?? 0} raw person detections · {metrics.occupancy.observed_track_count ?? metrics.occupancy.count} observed tracks{metrics.occupancy.temporally_carried_track_count ? ` · ${metrics.occupancy.temporally_carried_track_count} briefly carried` : ''}. Active tracks may miss or double-count people under occlusion, camera motion, or detector error; this is not a unique-person count.</p>
              </>
            ) : <p className="mt-1 text-predix-muted">An estimated active-track count will appear when the first analyzed frame arrives. It is not a unique-person count.</p>}
          </div>
          <div className="rounded-lg border border-predix-border bg-predix-surface/40 p-3 text-xs">
            <p className="font-semibold text-white">Alerts and zone</p>
            <p className="mt-1 text-predix-muted">Security alerts are unavailable because no validated suspicious-object model is configured. Generic object labels do not trigger alerts. Live zone status appears after you configure a polygon.</p>
          </div>
          <div className="rounded-lg border border-predix-border bg-predix-surface/40 p-3 text-xs">
            <p className="font-semibold text-white">Active occupancy signal alerts</p>
            {metrics?.occupancy_alerts?.length ? (
              <div className="mt-2 space-y-2">
                {metrics.occupancy_alerts.map((alert) => (
                  <div key={alert.alert_id} className="rounded border border-predix-border bg-predix-bg/60 p-2">
                    <div className="flex items-center justify-between gap-2">
                      <p className={`font-mono ${alert.severity === 'CRITICAL' ? 'text-predix-red' : alert.severity === 'WARNING' ? 'text-predix-amber' : 'text-predix-cyan'}`}>{alert.severity} · {alert.zone} · {alert.status.toUpperCase()}</p>
                      <time className="text-[9px] text-predix-muted" dateTime={alert.timestamp}>{new Date(alert.timestamp).toLocaleTimeString()}</time>
                    </div>
                    <p className="mt-1 text-predix-text">{alert.signal.replaceAll('_', ' ')}</p>
                    {alert.supporting_evidence.map((evidence) => <p key={evidence.signal} className="mt-1 text-[10px] text-predix-muted">Evidence: {evidence.description}</p>)}
                    <p className="mt-1 text-[10px] text-predix-text">{alert.recommendation}</p>
                    <p className="mt-1 text-[9px] text-predix-muted">Confidence not applicable to this rule. {alert.limitations}</p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-predix-muted">No current configured occupancy signal. Configure a zone capacity to enable capacity alerts; deviation alerts require a sufficient baseline.</p>
            )}
            <p className="mt-2 text-[10px] text-predix-muted">Severity reflects operator-configured occupancy thresholds and measured deviations. These are grouped occupancy signals, not incident or suspicious-object alerts, and have not been validated against labeled anomaly events.</p>
          </div>
          <div className="rounded-lg border border-predix-amber/25 bg-predix-surface/40 p-3 text-xs" aria-label="Live zone review cues">
            <div className="flex items-center justify-between gap-2">
              <p className="font-semibold text-white">Zones with configured review cues</p>
              <span className="font-mono text-[10px] text-predix-muted">{zoneReviewCues.length}</span>
            </div>
            <p className="mt-1 text-[9px] text-predix-muted">Ordered by configured capacity/deviation rule category for human review. This is not an incident-risk ranking.</p>
            {zoneReviewCues.length ? (
              <ul className="mt-2 space-y-2">
                {zoneReviewCues.map((zone) => (
                  <li key={zone.zone_id} className="rounded border border-predix-border bg-predix-bg/60 p-2">
                    <p className="flex items-center justify-between gap-2 font-semibold text-white">
                      {zone.name}
                      <span className="shrink-0 font-mono text-[9px] text-predix-amber">{zone.security_attention.status.replaceAll('_', ' ').toUpperCase()}</span>
                    </p>
                    {zone.security_attention.recommendation && <p className="mt-1 text-[10px] text-predix-text">{zone.security_attention.recommendation}</p>}
                    {zone.security_attention.signals?.map((signal) => (
                      <p key={signal.signal} className="mt-1 text-[9px] text-predix-muted">Evidence: {signal.signal.replaceAll('_', ' ')}{signal.status ? ` · ${signal.status}` : ''}{signal.evidence ? ` · ${signal.evidence}` : ''}</p>
                    ))}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-[10px] text-predix-muted">No configured review cue is available. Missing or absent cues are not a safety determination.</p>
            )}
          </div>
          {isInactive ? (
            <button type="button" onClick={inputMode === 'rtsp' ? startRtsp : inputMode === 'hls' ? startHls : startLive} disabled={(inputMode === 'rtsp' && !rtspUrl.trim()) || (inputMode === 'hls' && (!hlsUrl.trim() || !nativeHlsSupported))} className="flex min-h-12 w-full items-center justify-center gap-2 rounded-lg bg-predix-cyan px-4 py-3 text-sm font-semibold text-predix-bg hover:bg-predix-cyan/90 disabled:cursor-not-allowed disabled:opacity-50">
              <Camera className="h-4 w-4" /> {inputMode === 'rtsp' ? 'Connect RTSP camera' : inputMode === 'hls' ? 'Connect HLS stream' : 'Start live camera'}
            </button>
          ) : (
            <button type="button" onClick={stopLive} className="flex min-h-12 w-full items-center justify-center gap-2 rounded-lg border border-predix-red/30 bg-predix-red/10 px-4 py-3 text-sm font-semibold text-predix-red hover:bg-predix-red/15">
              {status === 'reconnecting' ? <RotateCw className="h-4 w-4" /> : <CircleStop className="h-4 w-4" />} Stop {inputMode === 'rtsp' ? 'RTSP source' : inputMode === 'hls' ? 'HLS stream' : 'live camera'}
            </button>
          )}
          {status === 'reconnecting' && <p className="text-center text-[10px] text-predix-muted">Bounded reconnect: attempt {Math.min(reconnectCount + 1, MAX_RECONNECTS)} of {MAX_RECONNECTS}</p>}
          <div className="rounded-lg border border-predix-border bg-predix-surface/40 p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <p className="font-semibold text-white">Recent live sessions</p>
              <button type="button" onClick={() => loadRecentSessions()} disabled={historyLoading} className="rounded border border-predix-border px-2 py-1 text-predix-cyan disabled:opacity-50">{historyLoading ? 'Loading…' : 'Refresh'}</button>
            </div>
            {historyError && <p role="alert" className="mt-2 text-predix-red">{historyError}</p>}
            {!historyError && recentSessions.length === 0 && <p className="mt-2 text-predix-muted">No stored live sessions yet.</p>}
            <ul className="mt-2 space-y-2">
              {recentSessions.map((session) => (
                <li key={session.session_id} className="border-t border-predix-border pt-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-predix-cyan">{session.status.replaceAll('_', ' ').toUpperCase()}</span>
                    <time className="text-[10px] text-predix-muted" dateTime={session.started_at}>{new Date(session.started_at).toLocaleString()}</time>
                  </div>
                  <p className="mt-1 text-predix-muted">{session.summary?.source_kind === 'rtsp' ? 'RTSP source' : session.summary?.source_kind === 'hls' ? 'HLS source' : 'Browser camera'} · {session.summary?.frames_processed ?? 0} frames · {session.summary?.total_detection_instances ?? 0} raw detections · {session.summary?.peak_estimated_visible_people ?? 0} peak estimated visible people</p>
                  {session.summary?.zone_occupancy?.some((zone) => zone.early_warning?.status === 'elevated') && <p className="mt-1 text-predix-amber">Occupancy early-warning cue recorded · human review rule only</p>}
                  {session.summary?.zone_occupancy?.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Stored occupancy history by zone">
                      {session.summary.zone_occupancy.map((zone) => (
                        <button
                          key={zone.zone_id}
                          type="button"
                          onClick={() => loadZoneHistory(session.session_id, zone.zone_id, zone.name)}
                          className="rounded border border-predix-border px-2 py-1 text-[10px] text-predix-cyan hover:bg-predix-cyan/10"
                        >View {zone.name} history</button>
                      ))}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => loadAlertHistory(session.session_id)}
                    className="mt-2 rounded border border-predix-border px-2 py-1 text-[10px] text-predix-cyan hover:bg-predix-cyan/10"
                  >View occupancy alert episodes</button>
                </li>
              ))}
            </ul>
            {selectedZoneHistory && (
              <div className="mt-3 rounded border border-predix-border bg-predix-bg/60 p-3" aria-live="polite">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold text-white">{selectedZoneHistory.zoneName} · stored zone history</p>
                  <button type="button" onClick={() => { zoneHistoryRequestRef.current?.abort(); setSelectedZoneHistory(null); setZoneHistoryError(null) }} className="text-[10px] text-predix-muted hover:text-white">Close</button>
                </div>
                {zoneHistoryLoading && <p className="mt-2 text-predix-muted">Loading saved occupancy records…</p>}
                {zoneHistoryError && <p role="alert" className="mt-2 text-predix-red">{zoneHistoryError}</p>}
                {!zoneHistoryLoading && !zoneHistoryError && (
                  <>
                    <p className="mt-2 text-[10px] text-predix-muted">Aggregate estimates from completed 15-second buckets. Frames and temporary track IDs are not stored.</p>
                    {selectedZoneHistory.observations.length === 0
                      ? <p className="mt-2 text-predix-muted">No completed occupancy buckets were stored for this zone.</p>
                      : <div className="mt-2 max-h-40 space-y-1 overflow-auto">
                        {selectedZoneHistory.observations.map((item) => (
                          <p key={item.bucket_start_seconds} className="font-mono text-[10px] text-predix-text">
                            {item.bucket_start_seconds}–{item.bucket_end_seconds}s · {Number(item.estimated_mean_visible_people).toFixed(1)} estimated visible people · {item.capacity_status}
                          </p>
                        ))}
                      </div>}
                    <p className="mt-3 font-semibold text-white">Evaluated crowd predictions</p>
                    {selectedZoneHistory.predictions.length === 0
                      ? <p className="mt-1 text-predix-muted">No forecast passed validation during this session.</p>
                      : <div className="mt-1 max-h-32 space-y-1 overflow-auto">
                        {selectedZoneHistory.predictions.map((item) => (
                          <p key={`${item.as_of_session_seconds}-${item.horizon_seconds}`} className="font-mono text-[10px] text-predix-text">
                            At {Number(item.as_of_session_seconds).toFixed(0)}s · +{item.horizon_seconds}s: {Number(item.forecast).toFixed(1)} ± {item.uncertainty_mae == null ? 'unavailable' : Number(item.uncertainty_mae).toFixed(1)} · {item.model}
                          </p>
                        ))}
                      </div>}
                  </>
                )}
              </div>
            )}
            {selectedAlertHistory && (
              <div className="mt-3 rounded border border-predix-border bg-predix-bg/60 p-3" aria-live="polite">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-semibold text-white">Stored occupancy-alert episodes</p>
                  <button type="button" onClick={() => { alertHistoryRequestRef.current?.abort(); setSelectedAlertHistory(null); setAlertHistoryError(null) }} className="text-[10px] text-predix-muted hover:text-white">Close</button>
                </div>
                {alertHistoryLoading && <p className="mt-2 text-predix-muted">Loading alert episodes…</p>}
                {alertHistoryError && <p role="alert" className="mt-2 text-predix-red">{alertHistoryError}</p>}
                {!alertHistoryLoading && !alertHistoryError && selectedAlertHistory.alerts.length === 0 && <p className="mt-2 text-predix-muted">No occupancy-signal episodes were recorded for this session.</p>}
                {!alertHistoryLoading && !alertHistoryError && selectedAlertHistory.alerts.length > 0 && (
                  <ul className="mt-2 max-h-48 space-y-2 overflow-auto">
                    {selectedAlertHistory.alerts.map((alert) => (
                      <li key={alert.episode_id} className="rounded border border-predix-border bg-predix-surface/50 p-2 text-[10px]">
                        <p className="font-mono text-white">{alert.severity} · {alert.zone} · {alert.status.replaceAll('_', ' ').toUpperCase()}</p>
                        <p className="mt-1 text-predix-muted">{alert.signal.replaceAll('_', ' ')} · {new Date(alert.first_seen_at).toLocaleString()}–{new Date(alert.last_seen_at).toLocaleTimeString()}</p>
                        {alert.supporting_evidence.map((evidence, index) => <p key={`${evidence.signal}-${index}`} className="mt-1 text-predix-text">Evidence: {evidence.description}</p>)}
                        <p className="mt-1 text-predix-text">{alert.recommendation}</p>
                        {alert.status === 'session_ended' && <p className="mt-1 text-predix-muted">The stream ended while this occupancy condition was active.</p>}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="mt-2 text-[9px] text-predix-muted">These are rule-based occupancy signals, not suspicious-object or incident alerts.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
