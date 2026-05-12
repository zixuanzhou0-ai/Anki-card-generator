import { describe, expect, it } from 'vitest'

import { getWorkerErrorActions } from './workerErrors'

describe('worker error actions', () => {
  it('offers subtitle-only recovery for YouTube rate limits', () => {
    const actions = getWorkerErrorActions('YOUTUBE_RATE_LIMIT').map((action) => action.id)

    expect(actions).toEqual(['use-subtitle-only', 'retry'])
  })

  it('uses fallback hints without duplicating actions', () => {
    const actions = getWorkerErrorActions('YOUTUBE_RATE_LIMIT', ['subtitle_only', 'skip_video_slicing']).map(
      (action) => action.id,
    )

    expect(actions).toEqual(['use-subtitle-only', 'retry', 'skip-video-slicing'])
  })

  it('routes model and TTS failures to the right settings pages', () => {
    expect(getWorkerErrorActions('MODEL_AUTH_FAILED').map((action) => action.id)).toEqual(['open-api-settings'])
    expect(getWorkerErrorActions('TTS_AUTH_FAILED').map((action) => action.id)).toEqual(['open-tts-settings'])
  })

  it('ignores unknown error codes safely', () => {
    expect(getWorkerErrorActions('SOMETHING_NEW')).toEqual([])
  })
})

