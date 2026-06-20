import { describe, expect, it } from 'vitest'

import { defaultRequest } from '../domain/options'
import type { GenerateRequest } from '../domain/types'
import {
  requestPatchInvalidatesExportArtifacts,
  requestPatchInvalidatesLearningArtifacts,
  requestPatchTouchesSourceMaterial,
} from './requestInvalidation'

describe('requestInvalidation', () => {
  it('invalidates extracted/generated artifacts when source material changes', () => {
    expect(requestPatchTouchesSourceMaterial({ source_url: 'https://example.com/video' })).toBe(true)
    expect(requestPatchTouchesSourceMaterial({ video_path: 'C:/video.mp4' })).toBe(true)
    expect(requestPatchTouchesSourceMaterial({ subtitle_path: 'C:/video.srt' })).toBe(true)
    expect(requestPatchTouchesSourceMaterial({ document_path: 'C:/legacy/document.pdf' })).toBe(true)
    expect(requestPatchInvalidatesLearningArtifacts({ source_mode: 'url' })).toBe(true)
    expect(requestPatchInvalidatesLearningArtifacts({ document_path: 'C:/legacy/document.pdf' })).toBe(true)
  })

  it('invalidates extracted/generated artifacts when learning or card contract changes', () => {
    const invalidatingPatches: Array<Partial<GenerateRequest>> = [
      { language: 'ja' },
      { level_mode: 'manual' },
      { level: 'C1' },
      { collection_levels: ['B2', 'C1'] },
      { template_id: 'immersive_v11' },
      { review_density: 'fast' },
      { card_types: ['phrase'] },
      { study_depth: 'deep' },
      { max_segments: 10 },
    ]

    for (const patch of invalidatingPatches) {
      expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(true)
    }
  })

  it('keeps existing artifacts for runtime permissions, preview-only, and provider settings', () => {
    const safePatches: Array<Partial<GenerateRequest>> = [
      { allow_private_network_url: true },
      { allow_ytdlp_remote_components: true },
      { local_path_access_confirmed: true },
      { reuse_ai_review_cache: true },
      {
        api_config: {
          ...defaultRequest.api_config,
          base_url: 'https://api.example.com/v1',
          api_key: 'secret',
          model: 'fast',
        },
      },
      { title: 'New display title' },
    ]

    for (const patch of safePatches) {
      expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(false)
    }
  })

  it('invalidates export artifacts, but not extracted cards, when runtime model or TTS config changes', () => {
    const patch: Partial<GenerateRequest> = {
      api_config: {
        ...defaultRequest.api_config,
        base_url: 'https://api.example.com/v1',
        api_key: 'secret',
        model: 'next-model',
      },
    }

    expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(false)
    expect(requestPatchInvalidatesExportArtifacts(patch)).toBe(true)
    expect(requestPatchInvalidatesExportArtifacts({ title: 'New display title' })).toBe(false)
  })
})
