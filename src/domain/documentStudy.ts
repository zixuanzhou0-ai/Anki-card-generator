import type {
  DocumentAnswerLanguage,
  DocumentAnswerLength,
  DocumentDepth,
  DocumentStudyMode,
  LanguageFocus,
} from './types'

export const documentStudyModeOptions: Array<{
  id: DocumentStudyMode
  label: string
  note: string
}> = [
  { id: 'knowledge', label: '知识吸收', note: '抽取概念、观点、术语和例子，做成知识问答卡' },
  { id: 'language_reading', label: '语言精读', note: '从英文文档里学习表达、词汇和语法框架' },
]

export const documentAnswerLanguageOptions: Array<{
  id: DocumentAnswerLanguage
  label: string
  note: string
}> = [
  { id: 'zh', label: '中文', note: '反面解释优先用自然中文' },
  { id: 'en', label: '英文', note: '反面答案和解释优先用英文' },
  { id: 'bilingual', label: '双语', note: '中文理解为主，保留关键英文术语' },
]

export const documentDepthOptions: Array<{
  id: DocumentDepth
  label: string
  note: string
}> = [
  { id: 'quick', label: '快速记忆', note: '短问题、短答案，适合快速过书' },
  { id: 'standard', label: '标准理解', note: '问题清楚，答案保留必要条件和例子' },
  { id: 'deep', label: '深入掌握', note: '强调边界、推理链和对比理解' },
]

export const documentAnswerLengthOptions: Array<{
  id: DocumentAnswerLength
  label: string
  note: string
}> = [
  { id: 'short', label: '短答案', note: '1 句为主，减少背诵负担' },
  { id: 'medium', label: '中等答案', note: '1-3 句，兼顾理解和复习效率' },
  { id: 'long', label: '详细答案', note: '允许更多解释，适合复杂概念' },
]

const validStudyModes = new Set<DocumentStudyMode>(documentStudyModeOptions.map((item) => item.id))
const validAnswerLanguages = new Set<DocumentAnswerLanguage>(documentAnswerLanguageOptions.map((item) => item.id))
const validDepths = new Set<DocumentDepth>(documentDepthOptions.map((item) => item.id))
const validAnswerLengths = new Set<DocumentAnswerLength>(documentAnswerLengthOptions.map((item) => item.id))

export const defaultDocumentStudyMode: DocumentStudyMode = 'knowledge'
export const defaultDocumentAnswerLanguage: DocumentAnswerLanguage = 'zh'
export const defaultDocumentDepth: DocumentDepth = 'standard'
export const defaultDocumentAnswerLength: DocumentAnswerLength = 'medium'
export const documentReadingFocusOptions: LanguageFocus[] = ['phrases', 'vocabulary', 'grammar']

export function normalizeDocumentStudyMode(value: unknown): DocumentStudyMode {
  return validStudyModes.has(value as DocumentStudyMode) ? (value as DocumentStudyMode) : defaultDocumentStudyMode
}

export function normalizeDocumentAnswerLanguage(value: unknown): DocumentAnswerLanguage {
  return validAnswerLanguages.has(value as DocumentAnswerLanguage)
    ? (value as DocumentAnswerLanguage)
    : defaultDocumentAnswerLanguage
}

export function normalizeDocumentDepth(value: unknown): DocumentDepth {
  return validDepths.has(value as DocumentDepth) ? (value as DocumentDepth) : defaultDocumentDepth
}

export function normalizeDocumentAnswerLength(value: unknown): DocumentAnswerLength {
  return validAnswerLengths.has(value as DocumentAnswerLength)
    ? (value as DocumentAnswerLength)
    : defaultDocumentAnswerLength
}

export function documentStudyModeLabel(value: unknown): string {
  const mode = normalizeDocumentStudyMode(value)
  return documentStudyModeOptions.find((item) => item.id === mode)?.label ?? '知识吸收'
}

export function documentAnswerLanguageLabel(value: unknown): string {
  const language = normalizeDocumentAnswerLanguage(value)
  return documentAnswerLanguageOptions.find((item) => item.id === language)?.label ?? '中文'
}

export function documentDepthLabel(value: unknown): string {
  const depth = normalizeDocumentDepth(value)
  return documentDepthOptions.find((item) => item.id === depth)?.label ?? '标准理解'
}

export function documentAnswerLengthLabel(value: unknown): string {
  const length = normalizeDocumentAnswerLength(value)
  return documentAnswerLengthOptions.find((item) => item.id === length)?.label ?? '中等答案'
}
