import { describe, expect, it } from 'vitest'

import { defaultRequest } from './defaults'
import { createDemoProject } from './demoProject'

describe('createDemoProject', () => {
  it('mirrors language reading document behavior in browser preview', () => {
    const project = createDemoProject({
      ...defaultRequest,
      source_mode: 'document',
      document_study_mode: 'language_reading',
      language_focus: ['phrases', 'listening', 'grammar'],
    })

    const card = project.segments[0].cards[0]
    expect(project.title).toBe('文档精读卡 Demo')
    expect(project.language_focus).toEqual(['phrases', 'grammar'])
    expect(project.segments[0].source_time).toBe('文档精读点 1')
    expect(card.type_label).toBe('文档精读卡')
    expect(card.enabled).toBe(false)
    expect(card.quality?.status).toBe('needs_review')
  })
})
