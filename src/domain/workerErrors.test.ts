import { describe, expect, it } from 'vitest'

import { getWorkerErrorActions } from './workerErrors'

describe('worker error actions', () => {
  it('routes YouTube rate limits to environment help and retry without missing-video fallback', () => {
    const actions = getWorkerErrorActions('YOUTUBE_RATE_LIMIT').map((action) => action.id)

    expect(actions).toEqual(['open-env-settings', 'retry'])
  })

  it('ignores deprecated missing-video fallback hints', () => {
    const actions = getWorkerErrorActions('YOUTUBE_RATE_LIMIT', ['subtitle_only', 'skip_video_slicing']).map(
      (action) => action.id,
    )

    expect(actions).toEqual(['open-env-settings', 'retry'])
  })

  it('routes model and TTS failures to the right settings pages', () => {
    expect(getWorkerErrorActions('MODEL_AUTH_FAILED').map((action) => action.id)).toEqual(['open-api-settings'])
    expect(getWorkerErrorActions('TTS_AUTH_FAILED').map((action) => action.id)).toEqual(['open-tts-settings'])
  })

  it('offers recovery actions for AI review JSON failures', () => {
    expect(getWorkerErrorActions('MODEL_REVIEW_BAD_JSON').map((action) => action.id)).toEqual([
      'open-api-settings',
      'retry',
    ])
  })

  it('keeps media/subtitle alignment mismatch recoverable without environment settings noise', () => {
    expect(getWorkerErrorActions('MEDIA_SUBTITLE_ALIGNMENT_MISMATCH').map((action) => action.id)).toEqual(['retry'])
  })

  it('keeps an explicit retry path for unknown worker failures', () => {
    expect(getWorkerErrorActions('UNKNOWN_WORKER_ERROR').map((action) => action.id)).toEqual(['retry'])
  })

  it('ignores unknown error codes safely', () => {
    expect(getWorkerErrorActions('SOMETHING_NEW')).toEqual([])
  })
})
