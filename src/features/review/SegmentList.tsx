import { useEffect, useRef } from 'react'
import { motion } from 'motion/react'

import type { DocumentStudyMode, Segment } from '../../domain/types'
import {
  candidateKindLabel,
  isDocumentReadingSegment,
  isKnowledgeSegment,
  phraseValueScore,
  segmentPhraseTitle,
  segmentTrainingFocus,
} from '../../domain/quality'

type SegmentListProps = {
  activeSegmentId: string | null
  motionDuration: number
  prefersReducedMotion: boolean
  segments: Segment[]
  documentStudyMode?: DocumentStudyMode
  onSelectSegment: (segmentId: string) => void
  onSetSegmentCardsEnabled: (enabled: boolean, segmentId?: string) => void
}

export function SegmentList({
  activeSegmentId,
  motionDuration,
  prefersReducedMotion,
  segments,
  documentStudyMode,
  onSelectSegment,
  onSetSegmentCardsEnabled,
}: SegmentListProps) {
  return (
    <div className="segment-list">
      {segments.map((segment, index) => {
        const score = phraseValueScore(segment.phrase_value_score)
        const totalCards = segment.cards.length
        const enabledCards = segment.cards.filter((card) => card.enabled).length
        const learningPointCount = Array.isArray(segment.learning_points) ? segment.learning_points.length : 0
        const allCardsEnabled = totalCards > 0 && enabledCards === totalCards
        const partiallyEnabled = enabledCards > 0 && enabledCards < totalCards
        const phraseTitle = segmentPhraseTitle(segment, documentStudyMode)
        const trainingFocus = segmentTrainingFocus(segment, documentStudyMode)
        const kindLabel = candidateKindLabel(segment.candidate_kind)
        const isReading = isDocumentReadingSegment(segment, documentStudyMode)
        const isKnowledge = isKnowledgeSegment(segment)
        const primaryCard = segment.cards[0]
        const reason =
          segment.phrase_reject_reason ||
          segment.phrase_decision_reason ||
          segment.phrase_card_focus ||
          primaryCard?.why_it_matters ||
          primaryCard?.why ||
          primaryCard?.teacher_note ||
          '等待模型或规则给出训练理由'
        return (
          <motion.div
            layout
            key={segment.id}
            className={[
              'segment-tab',
              segment.id === activeSegmentId ? 'selected' : '',
              allCardsEnabled ? 'cards-selected' : '',
              partiallyEnabled ? 'cards-partial' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: motionDuration,
              delay: prefersReducedMotion ? 0 : Math.min(index, 7) * 0.025,
            }}
            whileTap={prefersReducedMotion ? undefined : { scale: 0.992 }}
          >
            <SegmentSelectBox
              checked={allCardsEnabled}
              disabled={totalCards === 0}
              label={`选择片段：${phraseTitle}`}
              partial={partiallyEnabled}
              onChange={(checked) => onSetSegmentCardsEnabled(checked, segment.id)}
            />
            <button className="segment-tab-content" type="button" onClick={() => onSelectSegment(segment.id)}>
              <span className="segment-tab-top">
                <span>{segment.source_time}</span>
                {score !== null ? <em className="segment-status usable">学习点 · {score}/5</em> : null}
              </span>
              {kindLabel ? <span className={`kind-chip kind-${segment.candidate_kind}`}>{kindLabel}</span> : null}
              <strong>{phraseTitle}</strong>
              <small>
                {learningPointCount > 1 ? `${learningPointCount} 个学习点 · ` : ''}
                {enabledCards}/{totalCards} 张已选
              </small>
              <small className="segment-focus">{isReading ? '精读动作' : isKnowledge ? '记忆动作' : '训练点'}：{trainingFocus}</small>
              <small className="segment-reason">{reason}</small>
            </button>
          </motion.div>
        )
      })}
      {segments.length === 0 ? (
        <div className="filter-empty-state">
          <strong>当前筛选下没有片段</strong>
          <span>切换到“全部卡片”可以查看完整生成结果。</span>
        </div>
      ) : null}
    </div>
  )
}

type SegmentSelectBoxProps = {
  checked: boolean
  disabled: boolean
  label: string
  partial: boolean
  onChange: (checked: boolean) => void
}

function SegmentSelectBox({ checked, disabled, label, partial, onChange }: SegmentSelectBoxProps) {
  const checkboxRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = partial
    }
  }, [partial])

  return (
    <label className={`segment-select ${partial ? 'partial' : ''}`} onClick={(event) => event.stopPropagation()}>
      <input
        ref={checkboxRef}
        aria-label={label}
        checked={checked}
        disabled={disabled}
        type="checkbox"
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
      <span className="segment-check" aria-hidden="true" />
    </label>
  )
}
