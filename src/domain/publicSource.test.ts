import { describe, expect, it } from 'vitest'

import { publicProjectSourceStatus, publicSourceModeFor } from './publicSource'

describe('publicSourceModeFor', () => {
  it('keeps only video modes public and routes restored document state to local video', () => {
    expect(publicSourceModeFor('local')).toBe('local')
    expect(publicSourceModeFor('url')).toBe('url')
    expect(publicSourceModeFor('document')).toBe('local')
    expect(publicSourceModeFor(undefined)).toBe('local')
  })
})

describe('publicProjectSourceStatus', () => {
  it('keeps local and URL projects public', () => {
    expect(publicProjectSourceStatus({ source_mode: 'local' })).toEqual({
      publicSourceMode: 'local',
      isPublicVideoProject: true,
      isHistoricalNonPublicProject: false,
      notice: '',
    })
    expect(publicProjectSourceStatus({ source_mode: 'url' }).publicSourceMode).toBe('url')
    expect(publicProjectSourceStatus({ source_mode: undefined }).publicSourceMode).toBe('local')
  })

  it('marks restored document projects as historical non-public projects', () => {
    const status = publicProjectSourceStatus({ source_mode: 'document' })

    expect(status.publicSourceMode).toBe('local')
    expect(status.isPublicVideoProject).toBe(false)
    expect(status.isHistoricalNonPublicProject).toBe(true)
    expect(status.notice).toContain('当前发布版只支持本地视频和视频链接')
  })
})
