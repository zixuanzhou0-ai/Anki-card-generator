import { describe, expect, it } from 'vitest'

import {
  cleanLocalPath,
  directGenerationSourceError,
  learningPointExtractionSourceError,
  localPathAccessPromptForRequest,
  mergeRepairResults,
  normalizeProjectTemplateForPublicSource,
  modelApiTestTitle,
  pathLines,
  sourceUrlLooksPrivate,
  stripProjectRuntimeSecrets,
  titleFromPath,
  ttsApiTestTitle,
  workerFailureDetailsSummary,
} from './controllerHelpers'
import type { ApiTestResult, EnvRepairResult, Project, TtsTestResult } from '../domain/types'

describe('controllerHelpers', () => {
  it('detects private URLs without blocking public URLs', () => {
    expect(sourceUrlLooksPrivate('https://www.youtube.com/watch?v=abc')).toBe(false)
    expect(sourceUrlLooksPrivate('https://localhost:8080/video.mp4')).toBe(true)
    expect(sourceUrlLooksPrivate('http://127.0.0.1:8080/video.mp4')).toBe(true)
    expect(sourceUrlLooksPrivate('http://192.168.1.10/video.mp4')).toBe(true)
    expect(sourceUrlLooksPrivate('http://172.20.0.3/video.mp4')).toBe(true)
    expect(sourceUrlLooksPrivate('http://8.8.8.8/video.mp4')).toBe(false)
    expect(sourceUrlLooksPrivate('not a url')).toBe(false)
  })

  it('strips runtime secrets before materializing UI inventory', () => {
    const project = {
      id: 'project',
      title: 'Project',
      segments: [],
      api_config: {
        provider: 'mimo',
        api_key: 'model-secret',
        tts_config: {
          enabled: true,
          provider: 'mimo',
          api_key: 'nested-tts-secret',
        },
      },
      tts_config: {
        enabled: true,
        provider: 'qwen',
        api_key: 'tts-secret',
      },
    } as unknown as Project

    const sanitized = stripProjectRuntimeSecrets(project) as Project & {
      api_config?: { api_key?: string; tts_config?: { api_key?: string } }
      tts_config?: { api_key?: string }
    }

    expect(sanitized).not.toBe(project)
    expect(sanitized.api_config?.api_key).toBe('')
    expect(sanitized.api_config?.tts_config?.api_key).toBe('')
    expect(sanitized.tts_config?.api_key).toBe('')
  })

  it('normalizes public video project template ids without changing card data', () => {
    const card = { id: 'card-1', kind: 'phrase', answer_summary: 'run the register', enabled: true }
    const segment = {
      id: 'seg-1',
      start: 1,
      end: 3,
      source_time: '00:00:01.000 - 00:00:03.000',
      text: 'Can you run the register for a minute?',
      duration: 2,
      recommendation: 4,
      phrase: 'run the register',
      cards: [card],
    }
    const project = {
      id: 'project',
      title: 'Project',
      source_mode: 'url',
      template_id: 'ciba_tianxia_v1',
      review_density: 'fast',
      segments: [segment],
    } as unknown as Project

    const normalized = normalizeProjectTemplateForPublicSource(project)

    expect(normalized).not.toBe(project)
    expect(normalized.template_id).toBe('immersive_v11')
    expect(normalized.review_density).toBe('fast')
    expect(normalized.segments).toBe(project.segments)
    expect(normalized.segments[0].cards[0]).toBe(card)
  })

  it('leaves already public V11 projects and hidden document template ids stable', () => {
    const videoProject = {
      id: 'video-project',
      title: 'Video Project',
      source_mode: 'local',
      template_id: 'immersive_v11',
      segments: [],
    } as unknown as Project
    const documentProject = {
      id: 'document-project',
      title: 'Document Project',
      source_mode: 'document',
      template_id: 'ciba_tianxia_v1',
      segments: [],
    } as unknown as Project

    expect(normalizeProjectTemplateForPublicSource(videoProject)).toBe(videoProject)
    expect(normalizeProjectTemplateForPublicSource(documentProject)).toBe(documentProject)
  })

  it('normalizes local paths and derives titles', () => {
    expect(cleanLocalPath('  "E:\\Videos\\clip.mp4"  ')).toBe('E:\\Videos\\clip.mp4')
    expect(titleFromPath("'E:\\Videos\\BBC Apples.srt'")).toBe('BBC Apples')
    expect(pathLines("E:\\one.mp4\n'E:\\two.srt'\n\n")).toEqual(['E:\\one.mp4', 'E:\\two.srt'])
  })

  it('keeps source input validation consistent for extraction and direct generation', () => {
    expect(
      learningPointExtractionSourceError({
        source_mode: 'url',
        source_url: '   ',
        video_path: '',
      }),
    ).toBe('请先输入 YouTube / 视频 URL。')
    expect(
      learningPointExtractionSourceError({
        source_mode: 'local',
        source_url: '',
        video_path: '',
      }),
    ).toBe('请先选择视频文件。SRT 可以手动选择，也可以放在视频同目录自动匹配。')
    expect(
      learningPointExtractionSourceError({
        source_mode: 'document',
        source_url: '',
        video_path: '',
      }),
    ).toBe('当前发布版只支持本地视频和视频链接。请选择视频素材。')

    expect(
      directGenerationSourceError(
        {
          batch_enabled: true,
          source_mode: 'url',
          source_url: '',
          document_path: '',
          video_path: '',
        },
        0,
      ),
    ).toBe('批量模式下还没有可生成的视频素材。请先选择视频文件夹或把视频链接加入批量列表。')
    expect(
      directGenerationSourceError(
        {
          batch_enabled: true,
          source_mode: 'url',
          source_url: '',
          document_path: '',
          video_path: '',
        },
        2,
      ),
    ).toBeNull()
    expect(
      directGenerationSourceError(
        {
          batch_enabled: false,
          source_mode: 'document',
          source_url: '',
          document_path: '',
          video_path: '',
        },
        0,
      ),
    ).toBe('当前发布版只支持本地视频和视频链接。请选择视频素材。')
    expect(
      directGenerationSourceError(
        {
          batch_enabled: false,
          source_mode: 'document',
          source_url: '',
          document_path: 'E:\\Docs\\source.md',
          video_path: '',
        },
        0,
      ),
    ).toBe('当前发布版只支持本地视频和视频链接。请选择视频素材。')
    expect(
      directGenerationSourceError(
        {
          batch_enabled: true,
          source_mode: 'document',
          source_url: '',
          document_path: 'E:\\Docs\\source.md',
          video_path: '',
        },
        3,
      ),
    ).toBe('当前发布版只支持本地视频和视频链接。请选择视频素材。')
    expect(
      directGenerationSourceError(
        {
          batch_enabled: false,
          source_mode: 'local',
          source_url: '',
          document_path: '',
          video_path: 'E:\\Videos\\clip.mp4',
        },
        0,
      ),
    ).toBeNull()
  })

  it('builds local path access prompts only for unconfirmed local file reads', () => {
    expect(
      localPathAccessPromptForRequest({
        source_mode: 'url',
        local_path_access_confirmed: false,
        video_path: 'E:\\Videos\\clip.mp4',
        subtitle_path: '',
        document_path: '',
      }),
    ).toBeNull()
    expect(
      localPathAccessPromptForRequest({
        source_mode: 'local',
        local_path_access_confirmed: true,
        video_path: 'E:\\Videos\\clip.mp4',
        subtitle_path: '',
        document_path: '',
      }),
    ).toBeNull()
    expect(
      localPathAccessPromptForRequest({
        source_mode: 'local',
        local_path_access_confirmed: false,
        video_path: '',
        subtitle_path: '',
        document_path: '',
      }),
    ).toBeNull()

    const prompt = localPathAccessPromptForRequest({
      source_mode: 'local',
      local_path_access_confirmed: false,
      video_path: 'E:\\Videos\\clip.mp4',
      subtitle_path: 'E:\\Videos\\clip.srt',
      document_path: '',
    })

    expect(prompt).toContain('本轮将读取以下本地文件路径')
    expect(prompt).toContain('视频：E:\\Videos\\clip.mp4')
    expect(prompt).toContain('字幕：E:\\Videos\\clip.srt')
    expect(prompt).toContain('请确认这是你主动选择或认可的素材')
  })

  it('summarizes blocked cards, audio failures, and audit paths', () => {
    const summary = workerFailureDetailsSummary({
      blocked_cards: [
        {
          source_time: '00:00:01.000 - 00:00:03.000',
          title: 'run the register',
          matched_text: '本地草稿，需要人工确认',
        },
      ],
      audio_failures: [
        {
          learning_point_id: 'lp-1',
          role: 'sentence_tts',
          expected_text: 'Can you run the register for a minute?',
        },
      ],
      audio_audit_path: 'E:\\ANKI\\audit.json',
    })

    expect(summary).toContain('需修复卡')
    expect(summary).toContain('run the register')
    expect(summary).toContain('失败音频')
    expect(summary).toContain('sentence_tts')
    expect(summary).toContain('audio_audit')
  })

  it('merges repair results into a single summary', () => {
    const left: EnvRepairResult = {
      ok: true,
      target: 'ffmpeg',
      summary: 'FFmpeg 已安装',
      actions: [{ id: 'ffmpeg', label: 'FFmpeg', status: 'success', detail: 'ok' }],
    }
    const right: EnvRepairResult = {
      ok: false,
      target: 'python_runtime',
      summary: 'Python 需要手动安装',
      actions: [{ id: 'python_runtime', label: 'Python', status: 'manual', detail: 'manual' }],
    }

    const merged = mergeRepairResults(left, right)

    expect(merged.ok).toBe(false)
    expect(merged.target).toBe('all')
    expect(merged.actions).toHaveLength(2)
    expect(merged.summary).toContain('需手动处理 1 个')
  })

  it('maps model and TTS test states to compact titles', () => {
    expect(modelApiTestTitle(null, true)).toBe('正在测试连接')
    expect(modelApiTestTitle(null, false)).toBe('尚未测试')
    expect(modelApiTestTitle({ ok: true } as ApiTestResult, false)).toBe('连接成功')
    expect(modelApiTestTitle({ ok: false, error_code: 'MODEL_QUOTA_EXCEEDED' } as ApiTestResult, false)).toBe(
      '配额或限流',
    )

    expect(ttsApiTestTitle(null, true, true)).toBe('正在测试 TTS')
    expect(ttsApiTestTitle(null, false, false)).toBe('TTS 已关闭')
    expect(ttsApiTestTitle({ ok: true } as TtsTestResult, false, true)).toBe('TTS 连接成功')
    expect(ttsApiTestTitle({ ok: false, error_code: 'TTS_CONNECTION_FAILED' } as TtsTestResult, false, true)).toBe(
      'TTS 网络异常',
    )
  })
})
