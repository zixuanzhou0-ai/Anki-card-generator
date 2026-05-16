import type { ChangeEvent, SyntheticEvent } from 'react'
import { motion } from 'motion/react'
import { Play } from 'lucide-react'

import type { Card, Segment, SegmentFilter } from '../../domain/types'
import {
  isKnowledgeSegment,
  knowledgeTypeLabel,
  phraseValueScore,
  phraseTypeLabel,
  qualityClass,
  qualityLabel,
  segmentMediaEnd,
  segmentMediaStart,
  segmentPhraseLabel,
  segmentReviewStatus,
  segmentStatusLabel,
  segmentTrainingFocus,
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
  const isKnowledge = isKnowledgeSegment(segment)
  const knowledgeCard = segment.cards.find((card) => card.type === 'knowledge') ?? segment.cards[0]
  const knowledgeType = knowledgeTypeLabel(segment.knowledge_type ?? knowledgeCard?.knowledge_type)
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
          <span className="label">{isKnowledge ? '正面问题' : '英文原句'}</span>
          <strong>{segment.text}</strong>
        </div>
        <div>
          <span className="label">{isKnowledge ? '知识点' : '重点词伙'}</span>
          <strong>{segmentPhraseLabel(segment)}</strong>
        </div>
      </div>

      {isKnowledge && knowledgeCard ? (
        <div className={`phrase-review-panel status-${segmentReviewStatus(segment)}`}>
          <div>
            <span>文档知识评审</span>
            <strong>
              {segmentStatusLabel(segmentReviewStatus(segment))}
              {knowledgeType ? ` · ${knowledgeType}` : ''}
            </strong>
          </div>
          <p>记忆动作：{segmentTrainingFocus(segment)}</p>
          {knowledgeCard.why_it_matters || knowledgeCard.why ? (
            <p>为什么值得记：{knowledgeCard.why_it_matters || knowledgeCard.why}</p>
          ) : null}
          {knowledgeCard.quality?.issues?.length ? (
            <p>待审提示：{knowledgeCard.quality.issues.join(' / ')}</p>
          ) : null}
        </div>
      ) : segment.phrase_review_status ||
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
          <p>训练点：{segmentTrainingFocus(segment)}</p>
          {segment.phrase_type ? <p>表达类型：{phraseTypeLabel(segment.phrase_type) || segment.phrase_type}</p> : null}
          {segment.phrase_decision_reason ? <p>推荐理由：{segment.phrase_decision_reason}</p> : null}
          {segment.phrase_reject_reason ? <p>拒绝 / 修复提示：{segment.phrase_reject_reason}</p> : null}
        </div>
      ) : null}

      <div className="card-editor-list">
        {segment.cards.length === 0 ? (
          <div className="segment-empty-note">
            <strong>这个片段没有生成可导出的卡</strong>
            <span>
              {segment.phrase_reject_reason ||
                segment.phrase_decision_reason ||
                (isKnowledge ? '模型或规则认为它暂时不适合做知识卡。' : '模型或规则认为它暂时不适合做精品词伙卡。')}
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
  const isKnowledgeCard = card.type === 'knowledge'
  const cardPhraseScore = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  const cardPhraseStatus = (card.phrase_review_status as SegmentFilter | undefined) ?? segmentReviewStatus(segment)
  const learningTarget = card.learning_target || card.learning_goal
  const whyItMatters = card.why_it_matters || card.why
  const howToUseIt = card.how_to_use_it || card.context

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
      {learningTarget || card.decision_reason || skippedEntries.length > 0 ? (
        <div className="card-plan" aria-label="卡片生成规划">
          <div>
            <span className={`role-badge ${card.card_role ?? 'primary'}`}>
              {card.card_role === 'specialist' ? '专项卡' : '主卡'}
            </span>
            {learningTarget ? <strong>{learningTarget}</strong> : null}
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
      {isKnowledgeCard ? (
        <div className={`phrase-card-review status-${cardPhraseStatus}`}>
          <span>{knowledgeTypeLabel(card.knowledge_type ?? segment.knowledge_type) || '知识卡'}</span>
          {learningTarget ? <strong>记忆动作：{learningTarget}</strong> : null}
          {whyItMatters ? <p>为什么值得记：{whyItMatters}</p> : null}
          {howToUseIt ? <p>适用语境：{howToUseIt}</p> : null}
          {card.quality?.issues?.length ? <p>待审提示：{card.quality.issues.join(' / ')}</p> : null}
        </div>
      ) : cardPhraseScore !== null || card.phrase_decision_reason || card.phrase_reject_reason || card.phrase_card_focus ? (
        <div className={`phrase-card-review status-${cardPhraseStatus}`}>
          <span>词伙分{cardPhraseScore !== null ? ` ${cardPhraseScore}/5` : ''}</span>
          {card.phrase_card_focus ? <strong>训练点：{card.phrase_card_focus}</strong> : null}
          {whyItMatters ? <p>为什么值得学：{whyItMatters}</p> : null}
          {howToUseIt ? <p>怎么用：{howToUseIt}</p> : null}
          {card.phrase_decision_reason ? <p>推荐理由：{card.phrase_decision_reason}</p> : null}
          {card.phrase_reject_reason ? <p>拒绝 / 修复提示：{card.phrase_reject_reason}</p> : null}
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
          {isKnowledgeCard ? '知识点' : '重点词伙'}
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
