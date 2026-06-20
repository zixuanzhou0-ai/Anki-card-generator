import { describe, expect, it } from 'vitest'

import { normalizeTemplateId, publicTemplateIdFor } from './templates'

describe('templates', () => {
  it('normalizes unknown template ids to immersive v11', () => {
    expect(normalizeTemplateId('unknown-template')).toBe('immersive_v11')
    expect(normalizeTemplateId('ciba_tianxia_v1')).toBe('ciba_tianxia_v1')
  })

  it('forces all public video template selections back to immersive v11', () => {
    expect(publicTemplateIdFor('ciba_tianxia_v1', 'local')).toBe('immersive_v11')
    expect(publicTemplateIdFor('dictionary', 'url')).toBe('immersive_v11')
    expect(publicTemplateIdFor('unknown-template', 'local')).toBe('immersive_v11')
    expect(publicTemplateIdFor('immersive_v11', undefined)).toBe('immersive_v11')
  })

  it('keeps hidden historical document template ids normalized without making them public', () => {
    expect(publicTemplateIdFor('ciba_tianxia_v1', 'document')).toBe('ciba_tianxia_v1')
    expect(publicTemplateIdFor('unknown-template', 'document')).toBe('immersive_v11')
  })
})
