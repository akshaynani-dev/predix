import assert from 'node:assert/strict'
import test from 'node:test'
import { buildVideoUploadUrl, deleteUploadedVideo, uploadVideo } from '../src/videoUploadApi.js'

function fakeUpload() {
  const request = { upload: {}, open: (...args) => { request.openArgs = args }, send: (body) => { request.body = body } }
  const formData = { values: [], append(...args) { this.values.push(args) } }
  return { request, formData, options: { createRequest: () => request, createFormData: () => formData } }
}

test('video upload URL appends the endpoint while preserving an API base path', () => {
  assert.equal(buildVideoUploadUrl('http://predix.local/'), 'http://predix.local/api/video/upload')
  assert.equal(buildVideoUploadUrl('https://predix.local/backend/'), 'https://predix.local/backend/api/video/upload')
})

test('video upload sends multipart file data, reports progress, and resolves the server session', async () => {
  const { request, formData, options } = fakeUpload()
  const progress = []
  const requestLifecycle = []
  const file = { name: 'clip.mp4' }
  const result = uploadVideo('http://predix.local', file, {
    ...options,
    onProgress: (value) => progress.push(value),
    onRequest: (value) => requestLifecycle.push(value),
  })

  assert.deepEqual(request.openArgs, ['POST', 'http://predix.local/api/video/upload', true])
  assert.deepEqual(formData.values, [['file', file]])
  request.upload.onprogress({ lengthComputable: false, loaded: 1, total: 2 })
  request.upload.onprogress({ lengthComputable: true, loaded: 1, total: 2 })
  request.status = 200
  request.responseText = JSON.stringify({ video_id: 'session-1', metadata: { duration: 3 } })
  request.onload()

  assert.deepEqual(await result, { video_id: 'session-1', metadata: { duration: 3 } })
  assert.deepEqual(progress, [{ loaded: 1, total: 2 }])
  assert.deepEqual(requestLifecycle, [request, null])
})

test('video upload surfaces server errors and oversized upload errors', async () => {
  for (const [status, responseText, message] of [
    [422, JSON.stringify({ detail: 'Unsupported codec.' }), 'Unsupported codec.'],
    [413, 'not json', 'Video exceeds the maximum allowed upload size.'],
  ]) {
    const { request, options } = fakeUpload()
    const result = uploadVideo('http://predix.local', {}, options)
    request.status = status
    request.responseText = responseText
    request.onload()
    await assert.rejects(result, new RegExp(message.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
})

test('video upload rejects malformed successful responses and cancellation distinctly', async () => {
  const malformed = fakeUpload()
  const malformedResult = uploadVideo('http://predix.local', {}, malformed.options)
  malformed.request.status = 200
  malformed.request.responseText = '{}'
  malformed.request.onload()
  await assert.rejects(malformedResult, /Invalid server response format/)

  const cancelled = fakeUpload()
  const cancelledResult = uploadVideo('http://predix.local', {}, cancelled.options)
  cancelled.request.onabort()
  await assert.rejects(cancelledResult, (error) => error.name === 'AbortError')
})

test('uploaded video deletion calls the scoped session endpoint', async () => {
  const calls = []
  await deleteUploadedVideo('http://predix.local', 'video-id', async (...args) => {
    calls.push(args)
    return { ok: true, status: 200 }
  })
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'http://predix.local/api/video/video-id')
  assert.equal(calls[0][1].method, 'DELETE')
})

test('failed deletion is surfaced so the UI can preserve the uploaded session reference', async () => {
  await assert.rejects(
    deleteUploadedVideo('http://predix.local', 'video-id', async () => ({
      ok: false,
      status: 503,
      json: async () => ({}),
    })),
    /Could not delete uploaded video \(503\)/,
  )
})

test('API deletion detail is preserved for actionable conflicts', async () => {
  await assert.rejects(
    deleteUploadedVideo('http://predix.local', 'video-id', async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: 'Cannot remove this video while analysis is running.' }),
    })),
    /analysis is running/,
  )
})
