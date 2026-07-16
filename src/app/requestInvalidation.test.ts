import { describe, expect, it } from 'vitest'

import { defaultRequest } from '../domain/options'
import type { GenerateRequest } from '../domain/types'
import {
  modelApiConfigChangeInvalidatesLearningArtifacts,
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
      { review_density: 'fast' },
      { card_types: ['phrase'] },
      { study_depth: 'deep' },
      { max_segments: 10 },
    ]

    for (const patch of invalidatingPatches) {
      expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(true)
    }
  })

  it('keeps card drafts when only the Anki template changes and invalidates export evidence', () => {
    const patch: Partial<GenerateRequest> = { template_id: 'immersive_v11' }

    expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(false)
    expect(requestPatchInvalidatesExportArtifacts(patch)).toBe(true)
  })

  it('keeps existing artifacts for runtime permissions, preview-only, and provider settings', () => {
    const safePatches: Array<Partial<GenerateRequest>> = [
      { allow_private_network_url: true },
      { allow_ytdlp_remote_components: true },
      { local_path_access_confirmed: true },
      { reuse_ai_review_cache: true },

      { title: 'New display title' },
    ]

    for (const patch of safePatches) {
      expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(false)
    }
  })

  it('invalidates learning artifacts when the model connection identity changes', () => {
    const next = {
      ...defaultRequest.api_config,
      base_url: 'https://api.example.com/v1/',
      api_key: 'rotated-secret',
      model: 'next-model',
    }

    expect(modelApiConfigChangeInvalidatesLearningArtifacts(defaultRequest.api_config, next)).toBe(true)
    expect(
      modelApiConfigChangeInvalidatesLearningArtifacts(defaultRequest.api_config, {
        ...defaultRequest.api_config,
        api_key: 'rotated-secret',
      }),
    ).toBe(false)
  })

  it('keeps learning artifacts for TTS-only changes while invalidating export evidence', () => {
    const ttsOnly = {
      ...defaultRequest.api_config,
      tts_config: {
        ...defaultRequest.api_config.tts_config,
        voice: 'new-voice',
      },
    }
    const patch: Partial<GenerateRequest> = { api_config: ttsOnly }

    expect(modelApiConfigChangeInvalidatesLearningArtifacts(defaultRequest.api_config, ttsOnly)).toBe(false)
    expect(requestPatchInvalidatesLearningArtifacts(patch)).toBe(false)
    expect(requestPatchInvalidatesExportArtifacts(patch)).toBe(true)
    expect(requestPatchInvalidatesExportArtifacts({ title: 'New display title' })).toBe(false)
  })
})
