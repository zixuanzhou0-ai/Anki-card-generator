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
    note: '逐句发现词伙、生词用法、语法、听辨和语气风险，只生成统一学习卡；默认先选推荐项，也可以全选可制卡项后再导出。',
    badge: '默认',
  },
]

export function normalizeSelectionStrategy(value: unknown): SelectionStrategy {
  return value === 'curated' || value === 'exhaustive' || value === 'catch_all'
    ? defaultSelectionStrategy
    : defaultSelectionStrategy
}
