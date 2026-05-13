import type { Level } from './types'

export const levels: Array<{ id: Level; label: string; note: string }> = [
  { id: 'A1', label: 'A1 入门', note: '基础表达' },
  { id: 'A2', label: 'A2 基础', note: '短句高频' },
  { id: 'B1', label: 'B1 日常交流', note: '自然口语' },
  { id: 'B2', label: 'B2 独立表达', note: '表达块' },
  { id: 'C1', label: 'C1 高阶表达', note: '语气和隐含义' },
  { id: 'C2', label: 'C2 接近母语', note: '细微语域' },
]

export const levelOrder: Level[] = levels.map((level) => level.id)

export function defaultCollectionLevels(level: Level): Level[] {
  const index = Math.max(0, levelOrder.indexOf(level))
  const lower = Math.max(0, index - 1)
  return levelOrder.slice(lower, index + 1)
}

export function normalizeCollectionLevels(value: unknown, currentLevel: Level): Level[] {
  if (!Array.isArray(value)) return defaultCollectionLevels(currentLevel)
  const selected = value.filter((item): item is Level => levelOrder.includes(item as Level))
  const unique = Array.from(new Set(selected))
  return unique.length
    ? unique.sort((a, b) => levelOrder.indexOf(a) - levelOrder.indexOf(b))
    : defaultCollectionLevels(currentLevel)
}
