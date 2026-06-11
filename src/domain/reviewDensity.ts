import type { ReviewDensity } from './types'

export type ReviewDensityOption = {
  id: ReviewDensity
  label: string
  note: string
  badge: string
}

export const defaultReviewDensity: ReviewDensity = 'full'

export const reviewDensityOptions: ReviewDensityOption[] = [
  {
    id: 'fast',
    label: '精简背面',
    note: '只保留音频、原句、重点词伙和当前语境义；适合高频刷卡。',
    badge: '低干扰',
  },
  {
    id: 'full',
    label: '完整背面',
    note: '保留解释、边界、迁移句和听辨提示；适合新卡精学。',
    badge: '默认',
  },
]

export function normalizeReviewDensity(value: unknown): ReviewDensity {
  return value === 'fast' || value === 'full' ? value : defaultReviewDensity
}
