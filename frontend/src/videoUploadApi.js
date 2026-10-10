export function buildVideoUploadUrl(apiUrl) {
  const url = new URL(apiUrl)
  url.pathname = `${url.pathname.replace(/\/+$/, '')}/api/video/upload`
  return url.toString()
}

export function uploadVideo(apiUrl, file, {
  createRequest = () => new XMLHttpRequest(),
  createFormData = () => new FormData(),
  onProgress = () => {},
  onRequest = () => {},
} = {}) {
  return new Promise((resolve, reject) => {
    let request
    const finish = (callback, value) => {
      onRequest(null)
      callback(value)
    }
    try {
      request = createRequest()
      const formData = createFormData()
      formData.append('file', file)
      onRequest(request)
      request.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress({ loaded: event.loaded, total: event.total })
        }
      }
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) {
          try {
            const payload = JSON.parse(request.responseText)
            if (!payload.video_id || !payload.metadata) throw new Error('missing required upload fields')
            finish(resolve, payload)
          } catch {
            finish(reject, new Error('Invalid server response format.'))
          }
          return
        }

        let message = 'Upload failed. Please try again.'
        try {
          const errorPayload = JSON.parse(request.responseText)
          if (errorPayload.detail) message = errorPayload.detail
          else if (request.status === 413) message = 'Video exceeds the maximum allowed upload size.'
        } catch {
          if (request.status === 413) message = 'Video exceeds the maximum allowed upload size.'
          else if (request.status === 0) message = 'Unable to connect to the PREDIX server.'
        }
        finish(reject, new Error(message))
      }
      request.onerror = () => finish(reject, new Error('Unable to connect to the PREDIX server.'))
      request.onabort = () => {
        const error = new Error('Upload cancelled.')
        error.name = 'AbortError'
        finish(reject, error)
      }
      request.open('POST', buildVideoUploadUrl(apiUrl), true)
      request.send(formData)
    } catch {
      finish(reject, new Error('Unable to connect to the PREDIX server.'))
    }
  })
}

export async function deleteUploadedVideo(apiUrl, videoId, fetchImpl = fetch) {
  const response = await fetchImpl(`${apiUrl}/api/video/${encodeURIComponent(videoId)}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || `Could not delete uploaded video (${response.status}).`)
  }
}
