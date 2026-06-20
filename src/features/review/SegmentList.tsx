import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'

import type { DocumentStudyMode, Segment } from '../../domain/types'
import {
  candidateKindLabel,
  isUsableCardForExport,
  phraseValueScore,
  clipText,
  segmentPhraseTitle,
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

const SEGMENT_LIST_INITIAL_LIMIT = 48
const SEGMENT_LIST_LOAD_STEP = 48

export function SegmentList({
  activeSegmentId,
  motionDuration,
  prefersReducedMotion,
  segments,
  documentStudyMode,
  onSelectSegment,
  onSetSegmentCardsEnabled,
}: SegmentListProps) {
  const [renderLimit, setRenderLimit] = useState(SEGMENT_LIST_INITIAL_LIMIT)
  const segmentWindowKey = `${segments.length}:${segments[0]?.id ?? ''}:${segments[segments.length - 1]?.id ?? ''}`

  useEffect(() => {
    setRenderLimit(SEGMENT_LIST_INITIAL_LIMIT)
  }, [segmentWindowKey])

  const renderedSegments = useMemo(() => segments.slice(0, renderLimit), [segments, renderLimit])
  const hiddenCount = Math.max(0, segments.length - renderedSegments.length)
  const layoutEnabled = renderedSegments.length <= SEGMENT_LIST_INITIAL_LIMIT

  return (
    <div className="segment-list">
      {renderedSegments.map((segment, index) => {
        const score = phraseValueScore(segment.phrase_value_score)
        const totalCards = segment.cards.length
        const exportableCards = segment.cards.filter((card) => isUsableCardForExport(segment, card)).length
        const enabledCards = segment.cards.filter((card) => card.enabled && isUsableCardForExport(segment, card)).length
        const repairRequiredCards = Math.max(0, totalCards - exportableCards)
        const allCardsEnabled = exportableCards > 0 && enabledCards === exportableCards
        const partiallyEnabled = enabledCards > 0 && enabledCards < exportableCards
        const phraseTitle = segmentPhraseTitle(segment, documentStudyMode)
        const kindLabel = candidateKindLabel(segment.candidate_kind)
        const primaryCard = segment.cards[0]
        const sourceText = clipText(segment.text || primaryCard?.english || primaryCard?.example || '', 150)
        return (
          <motion.div
            layout={layoutEnabled}
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
              disabled={exportableCards === 0}
              label={`选择片段：${phraseTitle}`}
              partial={partiallyEnabled}
              onChange={(checked) => onSetSegmentCardsEnabled(checked, segment.id)}
            />
            <button className="segment-tab-content" type="button" onClick={() => onSelectSegment(segment.id)}>
              <span className="segment-tab-top">
                <span>{segment.source_time}</span>
                {repairRequiredCards > 0 ? (
                  <em className="segment-status blocked">需修复 {repairRequiredCards}</em>
                ) : score !== null ? (
                  <em className="segment-status usable">学习点 · {score}/5</em>
                ) : null}
              </span>
              {kindLabel ? <span className={`kind-chip kind-${segment.candidate_kind}`}>{kindLabel}</span> : null}
              <strong>{phraseTitle}</strong>
              <small>
                {enabledCards}/{exportableCards} 张可导出
                {repairRequiredCards > 0 ? ` · 需修复 ${repairRequiredCards}` : ''}
              </small>
              {sourceText ? <small className="segment-reason">{sourceText}</small> : null}
            </button>
          </motion.div>
        )
      })}
      {hiddenCount > 0 ? (
        <button
          className="segment-list-more"
          type="button"
          onClick={() => setRenderLimit((current) => current + SEGMENT_LIST_LOAD_STEP)}
        >
          显示更多 {Math.min(hiddenCount, SEGMENT_LIST_LOAD_STEP)} 条
        </button>
      ) : null}
      {segments.length === 0 ? (
        <div className="filter-empty-state">
          <strong>当前筛选下没有片段</strong>
          <span>切换到“全部片段”可以查看完整生成结果。</span>
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
