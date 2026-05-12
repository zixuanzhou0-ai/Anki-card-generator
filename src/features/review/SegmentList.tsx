import { motion } from 'motion/react'

import type { Segment } from '../../domain/types'
import {
  phraseValueScore,
  segmentPhraseTitle,
  segmentReviewStatus,
  segmentStatusLabel,
} from '../../domain/quality'

type SegmentListProps = {
  activeSegmentId: string | null
  motionDuration: number
  prefersReducedMotion: boolean
  segments: Segment[]
  onSelectSegment: (segmentId: string) => void
}

export function SegmentList({
  activeSegmentId,
  motionDuration,
  prefersReducedMotion,
  segments,
  onSelectSegment,
}: SegmentListProps) {
  return (
    <div className="segment-list">
      {segments.map((segment, index) => {
        const status = segmentReviewStatus(segment)
        const score = phraseValueScore(segment.phrase_value_score)
        return (
          <motion.button
            layout
            type="button"
            key={segment.id}
            className={`segment-tab ${segment.id === activeSegmentId ? 'selected' : ''}`}
            onClick={() => onSelectSegment(segment.id)}
            initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: motionDuration,
              delay: prefersReducedMotion ? 0 : Math.min(index, 7) * 0.025,
            }}
            whileTap={prefersReducedMotion ? undefined : { scale: 0.992 }}
          >
            <span className="segment-tab-top">
              <span>{segment.source_time}</span>
              <em className={`segment-status ${status}`}>
                {segmentStatusLabel(status)}
                {score !== null ? ` · ${score}/5` : ''}
              </em>
            </span>
            <strong>{segmentPhraseTitle(segment)}</strong>
            <small>
              {segment.cards.filter((card) => card.enabled).length} 张卡 · 推荐 {segment.recommendation}/5
            </small>
            <small className="segment-reason">
              {segment.phrase_reject_reason ||
                segment.phrase_decision_reason ||
                segment.phrase_card_focus ||
                '等待模型或规则给出推荐理由'}
            </small>
          </motion.button>
        )
      })}
      {segments.length === 0 ? (
        <div className="filter-empty-state">
          <strong>当前筛选下没有片段</strong>
          <span>切换到“全部”可以查看完整生成结果。</span>
        </div>
      ) : null}
    </div>
  )
}
