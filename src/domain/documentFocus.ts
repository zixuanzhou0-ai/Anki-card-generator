import type { DocumentFocus } from './types'

export const documentFocusOptions: Array<{
  id: DocumentFocus
  label: string
  note: string
  defaultOn: boolean
}> = [
  { id: 'concepts', label: '核心概念', note: '抽取必须理解的概念和机制', defaultOn: true },
  { id: 'arguments', label: '观点论证', note: '保留作者观点、理由和推导链', defaultOn: true },
  { id: 'terms', label: '术语定义', note: '整理专有术语、定义和边界', defaultOn: true },
  { id: 'examples', label: '例子案例', note: '把关键例子变成可回忆线索', defaultOn: false },
]

const validDocumentFocus = new Set<DocumentFocus>(documentFocusOptions.map((item) => item.id))

export const defaultDocumentFocus = documentFocusOptions
  .filter((item) => item.defaultOn)
  .map((item) => item.id)

export function normalizeDocumentFocus(value: unknown): DocumentFocus[] {
  if (!Array.isArray(value)) return defaultDocumentFocus
  const normalized = value.filter((item): item is DocumentFocus => validDocumentFocus.has(item as DocumentFocus))
  return normalized.length ? Array.from(new Set(normalized)) : defaultDocumentFocus
}

export function documentFocusSummary(value: unknown): string {
  return normalizeDocumentFocus(value)
    .map((focus) => documentFocusOptions.find((item) => item.id === focus)?.label ?? focus)
    .join(' / ')
}
