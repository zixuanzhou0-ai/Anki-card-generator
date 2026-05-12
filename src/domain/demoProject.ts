import type { GenerateRequest, Project, Segment } from './types'
import { cardOptions, levels } from './options'

export function createDemoProject(request: GenerateRequest): Project {
  if (request.source_mode === 'document') {
    const segment: Segment = {
      id: 'doc_demo_001',
      start: 0,
      end: 0,
      source_time: '文档知识点 1',
      text: 'What is spaced repetition and why does it improve long-term memory?',
      duration: 0,
      recommendation: 5,
      phrase: 'spaced repetition',
      cards: [
        {
          id: 'doc_demo_001_knowledge',
          type: 'knowledge',
          type_label: '知识卡',
          enabled: true,
          english: 'What is spaced repetition and why does it improve long-term memory?',
          chinese: '间隔重复会在遗忘前重新唤起记忆，让长期记忆更稳固。',
          phrase: 'spaced repetition',
          definition: '一种把复习安排在逐渐拉长的时间间隔中的学习方法。',
          collocations: 'spaced repetition system; review interval; active recall',
          context: '适合从文章、教材、讲义中抽取核心概念和可复习问题。',
          example: 'Anki uses spaced repetition to schedule the next review.',
          chinese_feel: '中文里更接近“隔一段时间再复习，而不是一次性死背”。',
          why: '这是理解 Anki 工作方式的基础概念，也容易迁移到任何学科。',
          difficulty: 'B1 日常交流',
          teacher_note: '这张卡要记住的是机制，不是背定义：为什么“隔开复习”更有效。',
          cloze: '____ improves long-term memory by scheduling reviews before forgetting.',
          quality: {
            score: 88,
            status: 'recommended',
            issues: [],
          },
        },
      ],
    }
    return {
      id: 'demo_document_project',
      title: request.title || '文档知识卡 Demo',
      source_mode: request.source_mode,
      source_url: '',
      source_info: null,
      video_path: '',
      subtitle_path: '',
      document_path: request.document_path || 'demo.md',
      language: request.language,
      level: request.level,
      collection_levels: request.collection_levels,
      template_id: request.template_id,
      content_toggles: request.content_toggles,
      card_types: ['knowledge'],
      segments: [segment],
      warning: '浏览器预览模式：真实文档解析和 apkg 导出需要在 Tauri 桌面端运行。',
      created_at: Date.now(),
    }
  }

  const sampleSegments: Segment[] = [
    {
      id: 'seg_demo_001',
      start: 754.2,
      end: 758.4,
      source_time: '00:12:34.200 - 00:12:38.400',
      text: "I'm not really in the mood right now.",
      duration: 4.2,
      recommendation: 5,
      phrase: 'in the mood',
      cards: [],
    },
    {
      id: 'seg_demo_002',
      start: 941.1,
      end: 945.3,
      source_time: '00:15:41.100 - 00:15:45.300',
      text: "Can we figure this out later?",
      duration: 4.2,
      recommendation: 4,
      phrase: 'figure out',
      cards: [],
    },
  ]

  sampleSegments.forEach((segment) => {
    segment.cards = request.card_types.map((type) => {
      const label = cardOptions.find((card) => card.id === type)?.label ?? type
      const cloze = segment.text.replace(new RegExp(segment.phrase, 'i'), '____')
      return {
        id: `${segment.id}_${type}`,
        type,
        type_label: label,
        enabled: true,
        english: segment.text,
        chinese:
          segment.id === 'seg_demo_001'
            ? '我现在真的没那个心情。'
            : '我们能不能晚点再把这件事弄明白？',
        phrase: segment.phrase,
        definition: `${segment.phrase} 是一个高频口语词伙，表达状态、处理问题或理解含义。`,
        collocations:
          segment.phrase === 'in the mood'
            ? 'not in the mood; in the mood for coffee; in the mood to talk'
            : 'figure it out; figure out why; figure out what happened',
        context: '常见于朋友、家人、同事之间的自然对话，语气比正式书面表达更松弛。',
        example:
          segment.phrase === 'in the mood'
            ? "I'm not in the mood to go out tonight."
            : "Give me a minute. I'll figure it out.",
        chinese_feel:
          segment.phrase === 'in the mood'
            ? '中文里更接近“没那个心情”。'
            : '中文里更接近“弄明白 / 想清楚”。',
        why: '这句短、真实、可迁移，适合用来训练听力和表达块。',
        difficulty: levels.find((level) => level.id === request.level)?.label ?? request.level,
        teacher_note: `这句值得学，因为 ${segment.phrase} 是真实口语里的高频表达。`,
        cloze,
        quality: {
          score: 86,
          status: 'recommended',
          issues: [],
        },
      }
    })
  })

  return {
    id: 'demo_project',
    title: request.title || 'Friends S01E01 Demo',
    source_mode: request.source_mode,
    source_url: request.source_url,
    source_info: request.source_mode === 'url' ? { title: 'URL Demo', webpage_url: request.source_url } : null,
    video_path: request.video_path || 'demo.mp4',
    subtitle_path: request.subtitle_path || 'demo.srt',
    language: request.language,
    level: request.level,
    collection_levels: request.collection_levels,
    template_id: request.template_id,
    content_toggles: request.content_toggles,
    card_types: request.card_types,
    segments: sampleSegments,
    warning: '浏览器预览模式：真实视频切片和 apkg 导出需要在 Tauri 桌面端运行。',
    created_at: Date.now(),
  }
}
