import type { GenerateRequest, Project, Segment } from './types'
import { cardOptions, levels } from './options'

export function createDemoProject(request: GenerateRequest): Project {
  if (request.source_mode === 'document') {
    const isReading = request.document_study_mode === 'language_reading'
    const segment: Segment = {
      id: 'doc_demo_001',
      start: 0,
      end: 0,
      source_time: isReading ? '文档精读点 1' : '文档知识点 1',
      text: isReading
        ? 'How does the document use “it turns out” to introduce a discovered result?'
        : 'What is spaced repetition and why does it improve long-term memory?',
      duration: 0,
      recommendation: isReading ? 4 : 5,
      phrase: isReading ? 'it turns out' : 'spaced repetition',
      knowledge_type: isReading ? 'terms' : 'concepts',
      document_card_kind: isReading ? 'language_reading' : 'knowledge',
      cards: [
        {
          id: 'doc_demo_001_knowledge',
          type: 'knowledge',
          type_label: isReading ? '文档精读卡' : '知识卡',
          enabled: true,
          english: isReading
            ? 'How does the document use “it turns out” to introduce a discovered result?'
            : 'What is spaced repetition and why does it improve long-term memory?',
          chinese: isReading ? '它用来引出后来发现或结果证明的内容。' : '间隔重复会在遗忘前重新唤起记忆，让长期记忆更稳固。',
          phrase: isReading ? 'it turns out' : 'spaced repetition',
          knowledge_type: isReading ? 'terms' : 'concepts',
          document_card_kind: isReading ? 'language_reading' : 'knowledge',
          content_kind: isReading ? 'phrase' : 'knowledge',
          definition: isReading ? '一个引出“结果证明 / 后来发现”的阅读表达。' : '一种把复习安排在逐渐拉长的时间间隔中的学习方法。',
          collocations: isReading
            ? 'it turns out that; as it turns out; turned out to be'
            : 'spaced repetition system; review interval; active recall',
          context: isReading ? '常见于论文、博客和说明文里，用来承接新的发现或结论。' : '适合从文章、教材、讲义中抽取核心概念和可复习问题。',
          example: isReading ? 'It turns out the simple method works in practice.' : 'Anki uses spaced repetition to schedule the next review.',
          chinese_feel: isReading ? '中文更像“结果发现 / 事实证明”。' : '中文里更接近“隔一段时间再复习，而不是一次性死背”。',
          why: isReading ? '阅读英文资料时经常遇到，能帮助识别作者在引出结论。' : '这是理解 Anki 工作方式的基础概念，也容易迁移到任何学科。',
          difficulty: 'B1 日常交流',
          estimated_level: 'B1',
          difficulty_reason: '高频表达，但需要理解语篇承接功能。',
          teacher_note: isReading
            ? '这张精读卡用于确认表达来自原文，并补一个你会再次遇到的语境。'
            : '这张卡要记住的是机制，不是背定义：为什么“隔开复习”更有效。',
          cloze: isReading ? '____ the simple method works in practice.' : '____ improves long-term memory by scheduling reviews before forgetting.',
          quality: {
            score: isReading ? 72 : 88,
            status: isReading ? 'needs_review' : 'recommended',
            issues: isReading ? ['文档精读卡建议确认表达是否来自原文'] : [],
          },
        },
      ],
    }
    return {
      id: 'demo_document_project',
      title: request.title || (isReading ? '文档精读卡 Demo' : '文档知识卡 Demo'),
      source_mode: request.source_mode,
      source_url: '',
      source_info: null,
      video_path: '',
      subtitle_path: '',
      document_path: request.document_path || 'demo.md',
      language: request.language,
      level_mode: request.level_mode,
      level: request.level,
      collection_levels: request.collection_levels,
      template_id: request.template_id,
      content_toggles: request.content_toggles,
      language_focus: isReading ? request.language_focus.filter((focus) => focus !== 'listening') : request.language_focus,
      document_focus: request.document_focus,
      document_study_mode: request.document_study_mode,
      document_answer_language: request.document_answer_language,
      document_depth: request.document_depth,
      document_answer_length: request.document_answer_length,
      study_depth: request.study_depth,
      material_context: {
        summary: isReading ? '演示文档正在训练英文资料里的表达理解。' : '演示文档介绍间隔重复为什么能提升长期记忆。',
        key_points: isReading ? ['识别引出结论的表达'] : ['间隔重复', '主动回忆', '复习间隔'],
        learning_opportunities: isReading ? ['词伙表达', '单词用法', '语法框架'] : ['核心概念', '术语定义'],
        source: 'heuristic',
      },
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
      phrase_type: 'spoken_phrase',
      content_kind: 'phrase',
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
      phrase_type: 'vocabulary_usage',
      content_kind: 'vocabulary',
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
        type_label: type === 'phrase' && segment.phrase_type === 'vocabulary_usage' ? '语境生词卡' : label,
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
        estimated_level: request.level,
        difficulty_reason: '按演示请求水平和表达迁移价值估计。',
        teacher_note: `这句值得学，因为 ${segment.phrase} 是真实口语里的高频表达。`,
        cloze,
        phrase_type: segment.phrase_type,
        content_kind: segment.content_kind,
        phrase_card_focus:
          segment.content_kind === 'vocabulary'
            ? '训练这个词在当前语境里的真实用法，而不是背词典义。'
            : '训练可迁移表达和中文语感。',
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
    level_mode: request.level_mode,
    level: request.level,
    collection_levels: request.collection_levels,
    template_id: request.template_id,
    content_toggles: request.content_toggles,
    language_focus: request.language_focus,
    document_focus: request.document_focus,
    document_study_mode: request.document_study_mode,
    document_answer_language: request.document_answer_language,
    document_depth: request.document_depth,
    document_answer_length: request.document_answer_length,
    study_depth: request.study_depth,
    material_context: {
      summary: '演示视频是朋友之间的自然对话，重点训练真实口语里的状态表达和处理问题的说法。',
      scene: '轻松但带情绪的日常对话',
      tone: '口语、自然、带一点犹豫',
      key_points: ['表达当前状态', '推迟处理问题'],
      learning_opportunities: ['词伙表达', '语境生词', '听力难点'],
      source: 'heuristic',
    },
    card_types: request.card_types,
    segments: sampleSegments,
    warning: '浏览器预览模式：真实视频切片和 apkg 导出需要在 Tauri 桌面端运行。',
    created_at: Date.now(),
  }
}
