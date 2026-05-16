import type { LanguageFocus } from './types'

export const languageFocusOptions: Array<{
  id: LanguageFocus
  label: string
  note: string
  defaultOn: boolean
}> = [
  { id: 'phrases', label: '词伙表达', note: '可迁移短语、搭配和口语块', defaultOn: true },
  { id: 'vocabulary', label: '单词用法', note: '真实语境里的词义、搭配和用法', defaultOn: false },
  { id: 'grammar', label: '语法框架', note: '句型、结构和可替换表达框架', defaultOn: false },
  { id: 'listening', label: '听力难点', note: '弱读、连读、语块和听音辨义', defaultOn: true },
]

const validFocus = new Set<LanguageFocus>(languageFocusOptions.map((item) => item.id))

export const defaultLanguageFocus = languageFocusOptions.filter((item) => item.defaultOn).map((item) => item.id)

export function normalizeLanguageFocus(value: unknown): LanguageFocus[] {
  if (!Array.isArray(value)) return defaultLanguageFocus
  const normalized = value.filter((item): item is LanguageFocus => validFocus.has(item as LanguageFocus))
  return normalized.length ? Array.from(new Set(normalized)) : defaultLanguageFocus
}

export function languageFocusSummary(value: unknown): string {
  const normalized = normalizeLanguageFocus(value)
  return normalized
    .map((focus) => languageFocusOptions.find((item) => item.id === focus)?.label ?? focus)
    .join(' / ')
}
