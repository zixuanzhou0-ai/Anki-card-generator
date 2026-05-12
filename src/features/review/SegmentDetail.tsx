import type { ChangeEvent, SyntheticEvent } from 'react'
import { motion } from 'motion/react'
import { Play } from 'lucide-react'

import type { Card, Segment, SegmentFilter } from '../../domain/types'
import {
  phraseValueScore,
  qualityClass,
  qualityLabel,
  segmentMediaEnd,
  segmentMediaStart,
  segmentPhraseLabel,
  segmentReviewStatus,
  segmentStatusLabel,
} from '../../domain/quality'

type SegmentDetailProps = {
  motionDuration: number
  prefersReducedMotion: boolean
  previewRate: number
  segment: Segment
  videoSrc: string
  onPreviewRateChange: (rate: number) => void
  onSetSegmentCardsEnabled: (enabled: boolean, segmentId: string) => void
  onUpdateCard: (segmentId: string, cardId: string, patch: Partial<Card>) => void
}

function handlePreviewLoaded(event: SyntheticEvent<HTMLVideoElement>, segment: Segment, previewRate: number) {
  const video = event.currentTarget
  video.currentTime = Math.max(0, segmentMediaStart(segment))
  video.playbackRate = previewRate
}

function handlePreviewTimeUpdate(event: SyntheticEvent<HTMLVideoElement>, segment: Segment, previewRate: number) {
  const video = event.currentTarget
  const start = segmentMediaStart(segment)
  const end = segmentMediaEnd(segment)
  video.playbackRate = previewRate
  if (video.currentTime >= end || video.currentTime < start) {
    video.currentTime = Math.max(0, start)
  }
}

export function SegmentDetail({
  motionDuration,
  prefersReducedMotion,
  previewRate,
  segment,
  videoSrc,
  onPreviewRateChange,
  onSetSegmentCardsEnabled,
  onUpdateCard,
}: SegmentDetailProps) {
  return (
    <div className="segment-detail">
      <div className="segment-toolbar">
        <div className="preview-rate" aria-label="预览播放速度">
          <span>播放</span>
          {[0.75, 1].map((rate) => (
            <button
              type="button"
              key={rate}
              className={previewRate === rate ? 'selected' : ''}
              onClick={() => onPreviewRateChange(rate)}
            >
              {rate}x
            </button>
          ))}
        </div>
        <div className="segment-actions">
          <button className="ghost-button" type="button" onClick={() => onSetSegmentCardsEnabled(true, segment.id)}>
            本段全选
          </button>
          <button className="ghost-button" type="button" onClick={() => onSetSegmentCardsEnabled(false, segment.id)}>
            本段停用
          </button>
        </div>
      </div>
      <div className={`media-preview ${videoSrc ? 'has-video' : ''}`} aria-label="片段视频预览">
        {videoSrc ? (
          <>
            <video
              key={`${segment.id}-${previewRate}`}
              controls
              playsInline
              preload="metadata"
              src={videoSrc}
              onLoadedMetadata={(event) => handlePreviewLoaded(event, segment, previewRate)}
              onTimeUpdate={(event) => handlePreviewTimeUpdate(event, segment, previewRate)}
            />
            <span className="media-time">{segment.media_source_time ?? segment.source_time}</span>
          </>
        ) : (
          <>
            <Play size={28} />
            <span>{segment.media_source_time ?? segment.source_time}</span>
          </>
        )}
      </div>
      <div className="segment-copy">
        <div>
          <span className="label">英文原句</span>
          <strong>{segment.text}</strong>
        </div>
        <div>
          <span className="label">重点词伙</span>
          <strong>{segmentPhraseLabel(segment)}</strong>
        </div>
      </div>

      {segment.phrase_review_status ||
      segment.phrase_decision_reason ||
      segment.phrase_reject_reason ||
      segment.phrase_card_focus ||
      segment.phrase_value_score !== undefined ? (
        <div className={`phrase-review-panel status-${segmentReviewStatus(segment)}`}>
          <div>
            <span>AI 词伙评审</span>
            <strong>
              {segmentStatusLabel(segmentReviewStatus(segment))}
              {phraseValueScore(segment.phrase_value_score) !== null
                ? ` · ${phraseValueScore(segment.phrase_value_score)}/5`
                : ''}
            </strong>
          </div>
          {segment.phrase_card_focus ? <p>{segment.phrase_card_focus}</p> : null}
          {segment.phrase_decision_reason ? <p>{segment.phrase_decision_reason}</p> : null}
          {segment.phrase_reject_reason ? <p>{segment.phrase_reject_reason}</p> : null}
        </div>
      ) : null}

      <div className="card-editor-list">
        {segment.cards.length === 0 ? (
          <div className="segment-empty-note">
            <strong>这个片段没有生成可导出的卡</strong>
            <span>
              {segment.phrase_reject_reason ||
                segment.phrase_decision_reason ||
                '模型或规则认为它暂时不适合做精品词伙卡。'}
            </span>
          </div>
        ) : null}
        {segment.cards.map((card) => (
          <CardEditor
            key={card.id}
            card={card}
            motionDuration={motionDuration}
            prefersReducedMotion={prefersReducedMotion}
            segment={segment}
            onUpdateCard={onUpdateCard}
          />
        ))}
      </div>
    </div>
  )
}

type CardEditorProps = {
  card: Card
  motionDuration: number
  prefersReducedMotion: boolean
  segment: Segment
  onUpdateCard: (segmentId: string, cardId: string, patch: Partial<Card>) => void
}

function CardEditor({ card, motionDuration, prefersReducedMotion, segment, onUpdateCard }: CardEditorProps) {
  const skippedEntries = Object.entries(card.skipped_card_types ?? {})
  const cardPhraseScore = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  const cardPhraseStatus = (card.phrase_review_status as SegmentFilter | undefined) ?? segmentReviewStatus(segment)

  return (
    <motion.article
      layout
      className={`card-editor card-${qualityClass(card)}`}
      key={card.id}
      initial={{ opacity: 0, y: prefersReducedMotion ? 0 : 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: motionDuration }}
    >
      <div className="card-editor-head">
        <label className="toggle card-toggle">
          <input
            type="checkbox"
            checked={card.enabled}
            onChange={() => onUpdateCard(segment.id, card.id, { enabled: !card.enabled })}
          />
          <span>{card.type_label}</span>
        </label>
        <div className="card-meta-row">
          <span className="difficulty">{card.difficulty}</span>
          <span className={`quality-badge ${qualityClass(card)}`}>
            {qualityLabel(card)}
            {typeof card.quality?.score === 'number' ? ` · ${card.quality.score}` : ''}
          </span>
        </div>
      </div>
      {card.learning_goal || card.decision_reason || skippedEntries.length > 0 ? (
        <div className="card-plan" aria-label="卡片生成规划">
          <div>
            <span className={`role-badge ${card.card_role ?? 'primary'}`}>
              {card.card_role === 'specialist' ? '专项卡' : '主卡'}
            </span>
            {card.learning_goal ? <strong>{card.learning_goal}</strong> : null}
          </div>
          {card.decision_reason ? <p>{card.decision_reason}</p> : null}
          {skippedEntries.length > 0 ? (
            <details className="skipped-card-types">
              <summary>已合并 {skippedEntries.length} 个低价值卡型</summary>
              <div>
                {skippedEntries.map(([type, reason]) => (
                  <span key={type}>
                    {type}: {reason}
                  </span>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
      {card.quality?.issues?.length ? (
        <div className="quality-issues" aria-label="卡片质量提示">
          {card.quality.issues.map((issue) => (
            <span key={issue}>{issue}</span>
          ))}
        </div>
      ) : null}
      {cardPhraseScore !== null || card.phrase_decision_reason || card.phrase_reject_reason || card.phrase_card_focus ? (
        <div className={`phrase-card-review status-${cardPhraseStatus}`}>
          <span>词伙分{cardPhraseScore !== null ? ` ${cardPhraseScore}/5` : ''}</span>
          {card.phrase_card_focus ? <strong>{card.phrase_card_focus}</strong> : null}
          {card.phrase_decision_reason ? <p>{card.phrase_decision_reason}</p> : null}
          {card.phrase_reject_reason ? <p>{card.phrase_reject_reason}</p> : null}
        </div>
      ) : null}
      <div className="edit-grid">
        <label>
          中文意思
          <textarea
            value={card.chinese}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
              onUpdateCard(segment.id, card.id, { chinese: event.target.value })
            }
          />
        </label>
        <label>
          重点词伙
          <textarea
            value={card.phrase}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
              onUpdateCard(segment.id, card.id, { phrase: event.target.value })
            }
          />
        </label>
        <label>
          释义 / 搭配
          <textarea
            value={`${card.definition}\n${card.collocations}`}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => {
              const [definition, ...rest] = event.target.value.split('\n')
              onUpdateCard(segment.id, card.id, {
                definition,
                collocations: rest.join('\n'),
              })
            }}
          />
        </label>
        <label>
          老师评语
          <textarea
            value={card.teacher_note}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
              onUpdateCard(segment.id, card.id, { teacher_note: event.target.value })
            }
          />
        </label>
      </div>
    </motion.article>
  )
}
