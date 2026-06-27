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
    label: '智能筛选',
    note: '逐句发现表达、生词、语法和听力难点，只输出可导出卡片，默认全选后由你决定导出。',
    badge: '默认',
  },
]

export function normalizeSelectionStrategy(value: unknown): SelectionStrategy {
  return value === 'curated' || value === 'exhaustive' || value === 'catch_all'
    ? defaultSelectionStrategy
    : defaultSelectionStrategy
}
