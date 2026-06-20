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
    label: '快速复读',
    note: '正面沿用沉浸复读，背面只保留原句、语境义、视频、原声和两段 TTS。',
    badge: '快速',
  },
  {
    id: 'full',
    label: '完整复读',
    note: '保留完整 V11 背面：用法、边界、迁移句和听辨提示，适合新卡精学。',
    badge: '完整',
  },
]

export function normalizeReviewDensity(value: unknown): ReviewDensity {
  return value === 'fast' || value === 'full' ? value : defaultReviewDensity
}
