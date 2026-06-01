import type { SelectionStrategy } from './types'

export type SelectionStrategyOption = {
  id: SelectionStrategy
  label: string
  note: string
  badge: string
}

export const defaultSelectionStrategy: SelectionStrategy = 'catch_all'

export const selectionStrategyOptions: SelectionStrategyOption[] = [
  {
    id: 'catch_all',
    label: '不漏优先',
    note: '先尽量发现表达、生词、语法和听力难点，再由评分决定推荐或待审。',
    badge: '默认',
  },
  {
    id: 'curated',
    label: '精选优先',
    note: '更严格地控制数量，只保留最值得直接复习的学习点。',
    badge: '少而精',
  },
  {
    id: 'exhaustive',
    label: '全量发现',
    note: '适合做素材审查，会保留更多边缘学习点，低分内容默认待审。',
    badge: '研究',
  },
]

export function normalizeSelectionStrategy(value: unknown): SelectionStrategy {
  return value === 'curated' || value === 'exhaustive' || value === 'catch_all'
    ? value
    : defaultSelectionStrategy
}
