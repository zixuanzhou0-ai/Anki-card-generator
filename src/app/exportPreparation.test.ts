import { describe, expect, it } from 'vitest'

import type { ApiConfig, Card, Project, Segment, TtsConfig } from '../domain/types'
import { buildReliabilityManifest } from '../domain/reliability'
import {
  buildProjectExportPayloadProject,
  canonicalReleaseApkgPathForOutputDirectory,
  defaultExportDirectoryForProject,
  defaultExportDirectoryForRequest,
  exportStartingStatusMessage,
  exportWorkerStartedProgressMessage,
  exportWorkerStartedStatusMessage,
  normalizeProjectForExportWorker,
  parentDirectoryFromFilePath,
  prepareProjectForExport,
  releaseApkgOutputGuardForProject,
  releaseApkgTargetForOutputDirectory,
  releaseCaseIdForProject,
  releaseRunSegmentForProject,
  releaseTargetRequiresColdMediaCacheReadsDisabled,
  videoExportTtsBlockReason,
} from './exportPreparation'

const baseCard: Card = {
  id: 'safe-card',
  type: 'knowledge',
  type_label: '知识卡',
  enabled: false,
  english: '为什么主动回忆比重读更稳？',
  chinese: '主动回忆会强化后续提取。',
  phrase: '主动回忆',
  definition: '通过提取练习巩固记忆。',
  collocations: '',
  context: '学习科学文档。',
  example: '',
  chinese_feel: '',
  why: '',
  difficulty: 'B1',
  teacher_note: '先回忆，再看答案。',
  cloze: '',
  quality: { score: 90, status: 'recommended', issues: [] },
}

function projectWithCards(cards: Card[]): Project {
  const segment: Segment = {
    id: 'doc-1',
    start: 0,
    end: 0,
    source_time: '文档知识点 1',
    text: '为什么主动回忆比重读更稳？',
    duration: 0,
    recommendation: 5,
    phrase: '主动回忆',
    cards,
  }
  return {
    id: 'doc-project',
    title: 'Document Project',
    source_mode: 'document',
    document_study_mode: 'knowledge',
    video_path: '',
    subtitle_path: '',
    language: 'en',
    level: 'B1',
    template_id: 'immersive',
    content_toggles: {
      daily: true,
      slang: true,
      sarcasm: true,
      business: true,
      culture: true,
      profanity: false,
      romance: false,
      rare: false,
    },
    card_types: ['knowledge'],
    segments: [segment],
    created_at: 1,
  }
}

describe('export directory picker defaults', () => {
  it('extracts the parent directory from Windows and POSIX file paths', () => {
    expect(parentDirectoryFromFilePath('E:\\ANKI\\materials\\source.mp4')).toBe('E:\\ANKI\\materials')
    expect(parentDirectoryFromFilePath('/tmp/materials/source.en.srt')).toBe('/tmp/materials')
    expect(parentDirectoryFromFilePath('source.mp4')).toBeNull()
    expect(parentDirectoryFromFilePath('')).toBeNull()
  })

  it('uses local request media paths as the APKG picker default', () => {
    const request = {
      source_mode: 'local' as const,
      video_path: 'E:\\ANKI\\materials\\source.mp4',
      subtitle_path: 'E:\\ANKI\\materials\\source.en.srt',
    }

    expect(defaultExportDirectoryForRequest(request)).toBe('E:\\ANKI\\materials')
    expect(defaultExportDirectoryForRequest({ ...request, video_path: '' })).toBe('E:\\ANKI\\materials')
    expect(defaultExportDirectoryForRequest({ ...request, source_mode: 'url' })).toBeNull()
  })

  it('uses local project source paths and falls back to source_info', () => {
    const localProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'local',
      video_path: '',
      subtitle_path: '',
      source_info: {
        video_path: 'E:\\ANKI\\material-cache\\source.mp4',
        subtitle_path: 'E:\\ANKI\\material-cache\\source.en.srt',
      },
    } as Project

    expect(defaultExportDirectoryForProject(localProject)).toBe('E:\\ANKI\\material-cache')
    expect(defaultExportDirectoryForProject({ ...localProject, source_mode: 'url' })).toBeNull()
  })

  it('computes the exact canonical APKG path for release case APKG directories', () => {
    expect(
      canonicalReleaseApkgPathForOutputDirectory(
        'E:\\ANKI\\test_runs\\video_release_hardening_20260620_000745\\cases\\local_srt_full1_cold\\apkg',
      ),
    ).toBe(
      'E:\\ANKI\\test_runs\\video_release_hardening_20260620_000745\\cases\\local_srt_full1_cold\\apkg\\local_srt_full1_cold.apkg',
    )
    expect(
      canonicalReleaseApkgPathForOutputDirectory(
        '/tmp/release_runs/video_release_hardening_20260620_000745/cases/youtube_a_full1_cold/apkg/',
      ),
    ).toBe(
      '/tmp/release_runs/video_release_hardening_20260620_000745/cases/youtube_a_full1_cold/apkg/youtube_a_full1_cold.apkg',
    )
    expect(
      releaseApkgTargetForOutputDirectory(
        'E:\\ANKI\\release_runs\\video_release_hardening_20260620_000745\\cases\\local_srt_full1_cold\\apkg',
      ),
    ).toMatchObject({
      caseId: 'local_srt_full1_cold',
      runSegment: 'video_release_hardening_20260620_000745',
      canonicalApkgPath:
        'E:\\ANKI\\release_runs\\video_release_hardening_20260620_000745\\cases\\local_srt_full1_cold\\apkg\\local_srt_full1_cold.apkg',
    })
  })

  it('rejects wrong directories inside release hardening runs without treating ordinary folders as release targets', () => {
    const runDir = 'E:\\ANKI\\release_runs\\video_release_hardening_20260620_000745'

    expect(canonicalReleaseApkgPathForOutputDirectory('E:\\ANKI\\material-cache')).toBeNull()
    expect(canonicalReleaseApkgPathForOutputDirectory(`${runDir}\\cases\\local_srt_full1_cold`)).toBeNull()
    expect(canonicalReleaseApkgPathForOutputDirectory(`${runDir}\\cases\\local_srt_full1_cold\\screenshots`)).toBeNull()
    expect(canonicalReleaseApkgPathForOutputDirectory(`${runDir}\\cases\\local_srt_full1_cold\\apkg\\nested`)).toBeNull()
    expect(canonicalReleaseApkgPathForOutputDirectory(`${runDir}\\cases\\not_a_release_case\\apkg`)).toBeNull()
    expect(canonicalReleaseApkgPathForOutputDirectory(`${runDir}\\cases\\bad-case\\apkg`)).toBeNull()
    expect(
      canonicalReleaseApkgPathForOutputDirectory(
        'E:\\ANKI\\release_runs\\video_smoke_20260620_000745\\cases\\local_srt_full1_cold\\apkg',
      ),
    ).toBeNull()
    expect(
      canonicalReleaseApkgPathForOutputDirectory(
        'E:\\ANKI\\release_runs\\video_release_hardening_20260620_000745\\nested\\cases\\local_srt_full1_cold\\apkg',
      ),
    ).toBeNull()
  })

  it('guards release matrix projects against exporting outside their case APKG directory', () => {
    const releaseProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      title: 'local_srt_full1_cold',
      source_mode: 'local',
    } as Project
    const expectedOutputDir =
      'E:\\ANKI\\test_runs\\video_release_hardening_20260620_033203\\cases\\local_srt_full1_cold\\apkg'

    expect(releaseCaseIdForProject(releaseProject)).toBe('local_srt_full1_cold')
    expect(releaseCaseIdForProject({ title: '普通项目', source_info: { case_id: 'youtube_a_full1_cold' } })).toBe(
      'youtube_a_full1_cold',
    )

    const ready = releaseApkgOutputGuardForProject(releaseProject, expectedOutputDir)
    expect(ready).toMatchObject({
      status: 'ready',
      releaseCaseId: 'local_srt_full1_cold',
      canonicalApkgPath: `${expectedOutputDir}\\local_srt_full1_cold.apkg`,
    })

    const documents = releaseApkgOutputGuardForProject(releaseProject, 'D:\\Administrator\\Documents')
    expect(documents).toMatchObject({
      status: 'blocked',
      reason: 'release_case_apkg_dir_required',
      releaseCaseId: 'local_srt_full1_cold',
    })
    if (documents.status === 'blocked') {
      expect(documents.statusMessage).toContain('cases\\local_srt_full1_cold\\apkg')
      expect(documents.statusMessage).toContain('Documents')
    }

    const otherCase = releaseApkgOutputGuardForProject(
      releaseProject,
      'E:\\ANKI\\test_runs\\video_release_hardening_20260620_033203\\cases\\youtube_a_full1_cold\\apkg',
    )
    expect(otherCase).toMatchObject({
      status: 'blocked',
      reason: 'release_case_apkg_case_mismatch',
      releaseCaseId: 'local_srt_full1_cold',
    })
  })

  it('guards release matrix projects against same-case APKG directories from the wrong run when run metadata is present', () => {
    const releaseProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      title: 'local_srt_full1_cold',
      source_mode: 'local',
      source_info: {
        case_id: 'local_srt_full1_cold',
        release_run_dir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260620_033203',
      },
    } as Project
    const expectedOutputDir =
      'E:\\ANKI\\test_runs\\video_release_hardening_20260620_033203\\cases\\local_srt_full1_cold\\apkg'
    const oldRunOutputDir =
      'E:\\ANKI\\test_runs\\video_release_hardening_20260620_000745\\cases\\local_srt_full1_cold\\apkg'

    expect(releaseRunSegmentForProject(releaseProject)).toBe('video_release_hardening_20260620_033203')
    expect(releaseApkgOutputGuardForProject(releaseProject, expectedOutputDir)).toMatchObject({
      status: 'ready',
      releaseCaseId: 'local_srt_full1_cold',
      canonicalApkgPath: `${expectedOutputDir}\\local_srt_full1_cold.apkg`,
    })
    const oldRun = releaseApkgOutputGuardForProject(releaseProject, oldRunOutputDir)
    expect(oldRun).toMatchObject({
      status: 'blocked',
      reason: 'release_case_apkg_run_mismatch',
      releaseCaseId: 'local_srt_full1_cold',
    })
    if (oldRun.status === 'blocked') {
      expect(oldRun.statusMessage).toContain('video_release_hardening_20260620_033203')
      expect(oldRun.statusMessage).toContain('video_release_hardening_20260620_000745')
    }
  })

  it('keeps ordinary projects on ordinary export behavior even if a release-looking directory is selected', () => {
    const ordinaryProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      title: '字幕素材',
      source_mode: 'local',
    } as Project
    const releaseOutputDir =
      'E:\\ANKI\\test_runs\\video_release_hardening_20260620_033203\\cases\\youtube_a_full1_cold\\apkg'

    expect(releaseApkgOutputGuardForProject(ordinaryProject, 'D:\\Administrator\\Documents')).toMatchObject({
      status: 'ready',
      releaseCaseId: null,
      canonicalApkgPath: null,
    })
    expect(releaseApkgOutputGuardForProject(ordinaryProject, releaseOutputDir)).toMatchObject({
      status: 'ready',
      releaseCaseId: null,
      releaseTarget: null,
      canonicalApkgPath: null,
    })
  })
})

describe('prepareProjectForExport', () => {
  it('removes superseded fallback drafts only when a verified usable replacement exists', () => {
    const safeCard: Card = {
      ...baseCard,
      id: 'safe-lp-1',
      enabled: true,
      learning_point_id: 'lp-1',
      verification_status: 'verified',
    }
    const fallbackCard: Card = {
      ...baseCard,
      id: 'fallback-lp-1',
      enabled: false,
      learning_point_id: 'lp-1',
      verification_status: 'needs_review',
      generation_source: 'fallback_from_selected_learning_point',
      quality: { score: 58, status: 'needs_review', issues: ['系统保底生成，需人工复核。'] },
    }
    const project = projectWithCards([safeCard])
    project.segments[0] = { ...project.segments[0], id: 'safe-segment', learning_point_id: 'lp-1' }
    project.segments.push({
      ...project.segments[0],
      id: 'fallback-segment',
      cards: [fallbackCard],
    })
    project.reliability_manifest = buildReliabilityManifest({
      outcomes: [{ learning_point_id: 'lp-1', status: 'verified', card_id: safeCard.id, blocker_codes: [] }],
      createdAt: 1,
    })

    const result = prepareProjectForExport(project)

    expect(result.status).toBe('ready')
    expect(result.project.segments.map((segment) => segment.id)).toEqual(['safe-segment'])
    expect(result.removedRepairRequiredCards).toBe(1)
    expect(result.selectedExportableCards).toBe(1)
    expect(result.statusMessage).toContain('已清理 1 张已被正式卡替代的旧保底草稿')
  })
  it('removes selected repair-required drafts and continues with remaining selected exportable cards', () => {
    const draft: Card = {
      ...baseCard,
      id: 'draft-card',
      enabled: true,
      chinese: '本地文档草稿，需要人工确认。',
      definition: '内部提示：正式导出前需要人工确认。',
      teacher_note: '请重新生成。',
      quality: { score: 65, status: 'needs_review', issues: ['自动草稿卡'] },
    }
    const safe: Card = { ...baseCard, enabled: true }

    const result = prepareProjectForExport(projectWithCards([draft, safe]))

    expect(result.status).toBe('ready')
    expect(result.removedRepairRequiredCards).toBe(1)
    expect(result.selectedExportableCards).toBe(1)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([false, true])
    expect(result.statusMessage).toContain('已移除 1 张需修复')
  })

  it('blocks before output-directory selection when all selected cards are repair drafts', () => {
    const draft: Card = {
      ...baseCard,
      id: 'draft-card',
      enabled: true,
      chinese: '本地文档精读草稿，需要人工确认。',
      definition: '内部提示：正式导出前需要人工确认。',
      teacher_note: '请重新生成。',
      quality: { score: 65, status: 'needs_review', issues: ['本地文档精读草稿，需要人工确认'] },
    }
    const safeButUnselected: Card = { ...baseCard, id: 'safe-unselected', enabled: false }

    const result = prepareProjectForExport(projectWithCards([draft, safeButUnselected]))

    expect(result.status).toBe('blocked')
    if (result.status === 'blocked') {
      expect(result.reason).toBe('selected_cards_all_repair_required')
    }
    expect(result.selectedExportableCards).toBe(0)
    expect(result.project.segments[0].cards.map((card) => card.enabled)).toEqual([false, false])
    expect(result.statusMessage).toContain('当前没有剩余可导出的正式卡')
  })

  it('materializes inventory candidates as unselected repair drafts instead of exportable cards', () => {
    const result = prepareProjectForExport({
      ...projectWithCards([]),
      learning_point_inventory: [
        {
          id: 'lp-doc',
          source_segment_id: 'doc-1',
          source_time: '文档知识点 1',
          source_sentence: '主动回忆要求学习者先尝试提取答案。',
          exact_span: '主动回忆',
          answer_core: '主动回忆',
          normalized_answer: '主动回忆',
          candidate_kind: 'contextual_vocab',
          phrase_type: 'vocabulary_usage',
          estimated_level: 'B1',
          value_score: 3,
          learning_action: '理解主动回忆的动作。',
          reason: '可查看但需要补全。',
          status: 'candidate_only',
        },
      ],
    })

    expect(result.status).toBe('blocked')
    expect(result.materializedDraftCards).toBe(1)
    expect(result.selectedExportableCards).toBe(0)
    expect(result.project.segments[0].cards[0].enabled).toBe(false)
    expect(result.statusMessage).toContain('当前没有可导出的正式卡')
    expect(result.statusMessage).toContain('请重新生成卡片')
    expect(result.statusMessage).not.toContain('文档卡')
  })

  it('exports a verified selected subset while retaining an unselected repair draft for later retry', () => {
    const safeCard: Card = {
      ...baseCard,
      id: 'safe-card',
      enabled: true,
      learning_point_id: 'lp-safe',
      verification_status: 'verified',
    }
    const fallbackCard: Card = {
      ...baseCard,
      id: 'fallback-card',
      enabled: false,
      learning_point_id: 'lp-missing',
      generation_source: 'fallback_from_selected_learning_point',
      verification_status: 'needs_review',
      quality: { score: 58, status: 'needs_review', issues: ['系统保底生成，需人工复核。'] },
    }
    const target = projectWithCards([safeCard, fallbackCard])
    target.reliability_manifest = buildReliabilityManifest({
      outcomes: [
        {
          learning_point_id: 'lp-safe',
          status: 'verified',
          card_id: 'safe-card',
          blocker_codes: [],
        },
        {
          learning_point_id: 'lp-missing',
          status: 'needs_review',
          card_id: 'fallback-card',
          blocker_codes: ['FALLBACK_CARD_REQUIRES_REVIEW'],
        },
      ],
    })

    const result = prepareProjectForExport(target)
    expect(result.status).toBe('ready')
    expect(result.selectedExportableCards).toBe(1)
    expect(result.project.reliability_manifest?.decision).toBe('block')

    const payloadProject = buildProjectExportPayloadProject({
      project: result.project,
      templateId: 'immersive',
      apiConfig: {
        provider: 'openai-compatible',
        base_url: '',
        api_key: '',
        model: '',
        capabilities: [],
        tts_config: {
          enabled: false,
          provider: 'disabled',
          base_url: '',
          api_key: '',
          model: '',
          voice: '',
          language: 'auto',
          sample_rate: 24000,
          bit_rate: 128000,
        },
      },
      ttsConfig: {
        enabled: false,
        provider: 'disabled',
        base_url: '',
        api_key: '',
        model: '',
        voice: '',
        language: 'auto',
        sample_rate: 24000,
        bit_rate: 128000,
      },
    })
    expect(payloadProject.reliability_manifest).toMatchObject({
      decision: 'pass',
      selected_point_count: 1,
      verified_count: 1,
      needs_review_count: 0,
    })
    expect(
      payloadProject.reliability_manifest?.selected_point_outcomes.map((outcome) => outcome.learning_point_id),
    ).toEqual(['lp-safe'])
  })

  it('fails closed when an actually selected exportable learning point still needs review', () => {
    const target = projectWithCards([
      {
        ...baseCard,
        id: 'review-card',
        enabled: true,
        learning_point_id: 'lp-missing',
        verification_status: 'verified',
      },
    ])
    target.reliability_manifest = buildReliabilityManifest({
      outcomes: [
        {
          learning_point_id: 'lp-missing',
          status: 'needs_review',
          card_id: 'review-card',
          blocker_codes: ['CARD_VERIFICATION_NOT_PASSED'],
        },
      ],
    })

    const result = prepareProjectForExport(target)
    expect(result.status).toBe('blocked')
    if (result.status === 'blocked') {
      expect(result.reason).toBe('reliability_gate_blocked')
      expect(result.reliabilityBlockerCodes).toContain('CARD_VERIFICATION_NOT_PASSED')
    }
    expect(result.statusMessage).toContain('可靠性门禁未通过')
  })
})

describe('buildProjectExportPayloadProject', () => {
  const disabledTts: TtsConfig = {
    enabled: false,
    provider: 'disabled',
    base_url: '',
    api_key: '',
    model: '',
    voice: '',
    language: 'auto',
    sample_rate: 24000,
    bit_rate: 128000,
  }
  const enabledTts: TtsConfig = {
    enabled: true,
    provider: 'gemini-vertex',
    base_url: 'https://aiplatform.googleapis.com',
    api_key: '',
    model: 'gemini-3.1-flash-tts-preview',
    voice: 'Kore',
    language: 'en-US',
    sample_rate: 24000,
    bit_rate: 128000,
    output_volume: 0.65,
  }
  const apiConfig: ApiConfig = {
    provider: 'gemini-vertex',
    base_url: 'https://aiplatform.googleapis.com',
    api_key: '',
    model: 'gemini-3.1-pro-preview',
    capabilities: ['json'],
    tts_config: disabledTts,
  }

  it('keeps legacy top-level tts_config aligned with current export api_config.tts_config', () => {
    const staleProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'url',
      template_id: 'immersive_v11',
      tts_config: disabledTts,
    } as Project & { tts_config: TtsConfig }

    const payloadProject = buildProjectExportPayloadProject({
      project: staleProject,
      templateId: 'immersive_v11',
      apiConfig,
      ttsConfig: enabledTts,
      ttsSemanticVerification: { require_pass_for_export: true },
    })

    expect(payloadProject.tts_config).toEqual(enabledTts)
    expect(payloadProject.api_config.tts_config).toEqual(enabledTts)
    expect(payloadProject.tts_semantic_verification?.require_pass_for_export).toBe(true)
  })

  it('strips stale ASR hard-gate fields and Ciba template ids from ordinary video export payloads', () => {
    const staleProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'local',
      video_path: 'E:/media/source.mp4',
      subtitle_path: 'E:/media/source.srt',
      template_id: 'ciba_tianxia_v1',
      tts_semantic_verification: {
        enabled: true,
        require_pass_for_export: true,
        asr_provider: 'whisper-cli',
      },
      asr_provider: 'whisper-cli',
      require_pass_for_export: true,
      enable_asr_quality_gate: true,
    } as Project & Record<string, unknown>
    const staleApiConfig = {
      ...apiConfig,
      tts_semantic_verification: {
        enabled: true,
        require_pass_for_export: true,
        asr_provider: 'whisper-cli',
      },
      asr_provider: 'whisper-cli',
      require_pass_for_export: true,
      enable_asr_quality_gate: true,
    } as ApiConfig & Record<string, unknown>

    const payloadProject = buildProjectExportPayloadProject({
      project: staleProject,
      templateId: 'ciba_tianxia_v1',
      apiConfig: staleApiConfig,
      ttsConfig: enabledTts,
    }) as Project & Record<string, unknown>
    const payloadApiConfig = payloadProject.api_config as ApiConfig & Record<string, unknown>

    expect(payloadProject.template_id).toBe('immersive_v11')
    expect(payloadProject.tts_semantic_verification).toBeUndefined()
    expect(payloadProject.asr_provider).toBeUndefined()
    expect(payloadProject.require_pass_for_export).toBeUndefined()
    expect(payloadProject.enable_asr_quality_gate).toBeUndefined()
    expect(payloadApiConfig.tts_semantic_verification).toBeUndefined()
    expect(payloadApiConfig.asr_provider).toBeUndefined()
    expect(payloadApiConfig.require_pass_for_export).toBeUndefined()
    expect(payloadApiConfig.enable_asr_quality_gate).toBeUndefined()
    expect(JSON.stringify(payloadProject)).not.toContain('whisper-cli')
    expect(JSON.stringify(payloadProject)).not.toContain('ciba_tianxia_v1')
  })

  it('keeps explicit semantic verification only when the export caller provides a fresh config', () => {
    const staleProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'url',
      template_id: 'immersive_v11',
      tts_semantic_verification: {
        enabled: true,
        require_pass_for_export: true,
        asr_provider: 'whisper-cli',
      },
    } as Project & Record<string, unknown>

    const payloadProject = buildProjectExportPayloadProject({
      project: staleProject,
      templateId: 'immersive_v11',
      apiConfig,
      ttsConfig: enabledTts,
      ttsSemanticVerification: {
        require_pass_for_export: true,
        asr_provider: 'asr-command',
      },
    })

    expect(payloadProject.tts_semantic_verification).toEqual({
      require_pass_for_export: true,
      asr_provider: 'asr-command',
    })
    expect(JSON.stringify(payloadProject)).not.toContain('whisper-cli')
  })

  it('adds persistent media cache read disables only when requested by a cold release export', () => {
    const releaseProject = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'url',
      release_case_id: 'youtube_b_quick20_cold',
    } as Project & Record<string, unknown>
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260620_000745'
    const releaseTarget = releaseApkgOutputGuardForProject(
      releaseProject,
      `${runDir}\\cases\\youtube_b_quick20_cold\\apkg`,
    )
    expect(releaseTarget.status).toBe('ready')
    const disableMediaCacheRead =
      releaseTarget.status === 'ready'
        ? releaseTargetRequiresColdMediaCacheReadsDisabled(releaseTarget.releaseTarget)
        : false

    const payloadProject = buildProjectExportPayloadProject({
      project: releaseProject,
      templateId: 'immersive_v11',
      apiConfig,
      ttsConfig: enabledTts,
      disableMediaCacheRead,
    }) as Project & Record<string, unknown>
    const payloadApiConfig = payloadProject.api_config as ApiConfig & Record<string, unknown>

    expect(payloadProject.disable_tts_cache_read).toBe(true)
    expect(payloadProject.disable_media_cache_read).toBe(true)
    expect(payloadApiConfig.disable_tts_cache_read).toBe(true)
    expect(payloadApiConfig.disable_media_cache_read).toBe(true)

    const ordinaryPayload = buildProjectExportPayloadProject({
      project: {
        ...projectWithCards([{ ...baseCard, enabled: true }]),
        source_mode: 'url',
      } as Project,
      templateId: 'immersive_v11',
      apiConfig,
      ttsConfig: enabledTts,
    }) as Project & Record<string, unknown>

    expect(ordinaryPayload.disable_tts_cache_read).toBeUndefined()
    expect(ordinaryPayload.disable_media_cache_read).toBeUndefined()
  })
})

describe('videoExportTtsBlockReason', () => {
  const disabledTts: TtsConfig = {
    enabled: false,
    provider: 'disabled',
    base_url: '',
    api_key: '',
    model: '',
    voice: '',
    language: 'auto',
    sample_rate: 24000,
    bit_rate: 128000,
  }
  const enabledTts: TtsConfig = {
    enabled: true,
    provider: 'gemini-vertex',
    base_url: 'https://aiplatform.googleapis.com',
    api_key: '',
    model: 'gemini-3.1-flash-tts-preview',
    voice: 'Kore',
    language: 'en-US',
    sample_rate: 24000,
    bit_rate: 128000,
    output_volume: 0.65,
  }

  it('blocks video export when TTS is disabled', () => {
    const project = { ...projectWithCards([{ ...baseCard, enabled: true }]), source_mode: 'url' } as Project

    expect(videoExportTtsBlockReason(project, disabledTts, null)).toContain('视频卡必须包含整句 TTS 和表达 TTS')
  })

  it('blocks video export when TTS config validation fails', () => {
    const project = { ...projectWithCards([{ ...baseCard, enabled: true }]), source_mode: 'local' } as Project

    expect(videoExportTtsBlockReason(project, enabledTts, '还没有填写 TTS 模型。')).toContain('当前 TTS 配置未通过')
  })

  it('allows video export when TTS is enabled and valid', () => {
    const project = { ...projectWithCards([{ ...baseCard, enabled: true }]), source_mode: 'url' } as Project

    expect(videoExportTtsBlockReason(project, enabledTts, null)).toBeNull()
  })

  it('allows document export without TTS', () => {
    const project = projectWithCards([{ ...baseCard, enabled: true }])

    expect(videoExportTtsBlockReason(project, disabledTts, null)).toBeNull()
  })
})

describe('normalizeProjectForExportWorker', () => {
  it('forces URL projects to export as video instead of transcript-only', () => {
    const project = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'url',
      url_import_mode: 'subtitles',
      skip_video_slicing: true,
    } as Project

    expect(normalizeProjectForExportWorker(project)).toMatchObject({
      source_mode: 'url',
      url_import_mode: 'video',
      skip_video_slicing: false,
    })
  })

  it('keeps local video export slicing enabled without adding URL identity', () => {
    const project = {
      ...projectWithCards([{ ...baseCard, enabled: true }]),
      source_mode: 'local',
      skip_video_slicing: true,
    } as Project

    const normalized = normalizeProjectForExportWorker(project)

    expect(normalized).toMatchObject({
      source_mode: 'local',
      skip_video_slicing: false,
    })
    expect('url_import_mode' in normalized).toBe(false)
  })

  it('leaves document projects unchanged for compatibility with hidden legacy flows', () => {
    const project = projectWithCards([{ ...baseCard, enabled: true }])

    expect(normalizeProjectForExportWorker(project)).toBe(project)
  })
})

describe('export status messages', () => {
  it('keeps the video export start message focused on media generation', () => {
    expect(exportStartingStatusMessage({ sourceMode: 'url', auto: false })).toBe('正在切视频、生成音频并打包 apkg。')
    expect(exportStartingStatusMessage({ sourceMode: 'local', auto: true })).toBe(
      '卡片正文已完成，正在自动生成音频、切片并打包 APKG。',
    )
  })

  it('keeps document and degraded-TTS messages distinct', () => {
    expect(exportStartingStatusMessage({ sourceMode: 'document', auto: false })).toBe('正在打包文档知识卡 apkg。')
    expect(exportStartingStatusMessage({ sourceMode: 'document', auto: false, ttsConfigError: '缺少 voice' })).toBe(
      'TTS 配置未通过，视频卡必须先修复整句 TTS 和表达 TTS：缺少 voice',
    )
    expect(exportStartingStatusMessage({ sourceMode: 'url', auto: false, ttsConfigError: '缺少 voice' })).not.toContain('跳过')
  })

  it('separates worker progress copy from status copy', () => {
    expect(exportWorkerStartedProgressMessage(false)).toBe('导出任务已在后台运行。你可以继续浏览当前卡片。')
    expect(exportWorkerStartedProgressMessage(true)).toBe('APKG 打包任务已在后台运行。')
    expect(exportWorkerStartedStatusMessage(false)).toBe('导出任务已在后台运行。导出期间不能再次生成或导出。')
    expect(exportWorkerStartedStatusMessage(true)).toBe('正在生成 APKG。导出期间不能再次生成或导出。')
  })
})
