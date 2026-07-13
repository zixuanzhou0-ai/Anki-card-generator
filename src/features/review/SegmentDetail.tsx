import type { ChangeEvent, SyntheticEvent } from 'react'
import { motion } from 'motion/react'
import { Play } from 'lucide-react'

import type { Card, DocumentStudyMode, PronunciationFieldChange, Segment } from '../../domain/types'
import {
  normalizePronunciationMeta,
  pronunciationBasisHint,
  spokenPronunciationLabel,
  standardPronunciationHint,
} from '../../domain/options'
import {
  candidateKindLabel,
  isDocumentReadingSegment,
  isKnowledgeSegment,
  knowledgeTypeLabel,
  phraseValueScore,
  phraseTypeLabel,
  qualityClass,
  qualityLabel,
  cardHasExportBlockingContent,
  isUsableCardForExport,
  segmentMediaEnd,
  segmentMediaStart,
  segmentPhraseLabel,
  segmentReviewStatus,
  segmentTrainingFocus,
} from '../../domain/quality'

type SegmentDetailProps = {
  motionDuration: number
  prefersReducedMotion: boolean
  previewRate: number
  segment: Segment
  videoSrc: string
  videoError?: string
  language?: string
  documentStudyMode?: DocumentStudyMode
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
  videoError,
  language,
  documentStudyMode,
  onSetSegmentCardsEnabled,
  onUpdateCard,
}: SegmentDetailProps) {
  const isKnowledge = isKnowledgeSegment(segment)
  const isReading = isDocumentReadingSegment(segment, documentStudyMode)
  const knowledgeCard = segment.cards.find((card) => card.type === 'knowledge') ?? segment.cards[0]
  const knowledgeType = knowledgeTypeLabel(segment.knowledge_type ?? knowledgeCard?.knowledge_type)
  const learningPoints = Array.isArray(segment.learning_points) ? segment.learning_points : []
  return (
    <div className="segment-detail">
      <div className="segment-toolbar">
        <div className="segment-actions">
          <button className="ghost-button" type="button" onClick={() => onSetSegmentCardsEnabled(true, segment.id)}>
            本段全选可导出
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
            {videoError ? (
              <small className="media-preview-error" role="alert">
                {videoError}
              </small>
            ) : null}
          </>
        )}
      </div>
      <div className="segment-copy">
        <div>
          <span className="label">{isKnowledge ? '正面问题' : '英文原句'}</span>
          <strong>{segment.text}</strong>
        </div>
        <div>
          <span className="label">{isReading ? '精读点' : isKnowledge ? '知识点' : '学习点'}</span>
          <strong>{segmentPhraseLabel(segment, documentStudyMode)}</strong>
        </div>
      </div>

      {learningPoints.length > 1 ? (
        <div className="learning-point-strip" aria-label="本句学习点">
          <span>本句 {learningPoints.length} 个学习点</span>
          <div>
            {learningPoints.map((point) => (
              <em key={point.id}>
                {candidateKindLabel(point.kind) || point.content_kind || '学习点'} ·{' '}
                {point.answer_core || point.exact_span}
              </em>
            ))}
          </div>
        </div>
      ) : null}

      {isKnowledge && knowledgeCard ? (
        <div className={`phrase-review-panel status-${segmentReviewStatus(segment)}`}>
          <div>
            <span>{isReading ? '文档精读学习点' : '文档知识学习点'}</span>
            <strong>{knowledgeType || '可导出卡片'}</strong>
          </div>
          <p>
            {isReading ? '精读动作' : '记忆动作'}：{segmentTrainingFocus(segment, documentStudyMode)}
          </p>
          {knowledgeCard.why_it_matters || knowledgeCard.why ? (
            <p>
              {isReading ? '为什么值得学' : '为什么值得记'}：{knowledgeCard.why_it_matters || knowledgeCard.why}
            </p>
          ) : null}
          {knowledgeCard.quality?.issues?.length ? <p>检查提示：{knowledgeCard.quality.issues.join(' / ')}</p> : null}
        </div>
      ) : segment.phrase_review_status ||
        segment.phrase_decision_reason ||
        segment.phrase_reject_reason ||
        segment.phrase_card_focus ||
        segment.phrase_value_score !== undefined ? (
        <div className={`phrase-review-panel status-${segmentReviewStatus(segment)}`}>
          <div>
            <span>学习点</span>
            <strong>
              可导出卡片
              {phraseValueScore(segment.phrase_value_score) !== null
                ? ` · ${phraseValueScore(segment.phrase_value_score)}/5`
                : ''}
            </strong>
          </div>
          <p>训练点：{segmentTrainingFocus(segment)}</p>
          {candidateKindLabel(segment.candidate_kind) ? (
            <p>候选类型：{candidateKindLabel(segment.candidate_kind)}</p>
          ) : null}
          {segment.phrase_type ? <p>表达类型：{phraseTypeLabel(segment.phrase_type) || segment.phrase_type}</p> : null}
          {segment.exact_span ? <p>原文 span：{segment.exact_span}</p> : null}
          {segment.answer_core ? <p>核心答案：{segment.answer_core}</p> : null}
          {segment.phrase_decision_reason ? <p>筛选理由：{segment.phrase_decision_reason}</p> : null}
          {segment.phrase_reject_reason ? <p>检查提示：{segment.phrase_reject_reason}</p> : null}
        </div>
      ) : null}

      <div className="card-editor-list">
        {segment.cards.length === 0 ? (
          <div className="segment-empty-note">
            <strong>这个片段没有生成可导出的卡</strong>
            <span>
              {segment.phrase_reject_reason ||
                segment.phrase_decision_reason ||
                (isReading
                  ? '模型或规则认为它暂时不适合做文档精读卡。'
                  : isKnowledge
                    ? '模型或规则认为它暂时不适合做知识卡。'
                    : '模型或规则认为它暂时不适合导出为学习卡。')}
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
            language={language}
            documentStudyMode={documentStudyMode}
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
  language?: string
  documentStudyMode?: DocumentStudyMode
  onUpdateCard: (segmentId: string, cardId: string, patch: Partial<Card>) => void
}

function pronunciationFieldLabel(field: PronunciationFieldChange['field']) {
  if (field === 'phonetic_ipa') return '标准读法'
  if (field === 'spoken_ipa') return '口语读法'
  if (field === 'source_spoken_ipa') return '推测原句读法'
  return '发音说明'
}

function pronunciationActionLabel(action: PronunciationFieldChange['action']) {
  if (action === 'hidden') return '已隐藏'
  if (action === 'cleared') return '已清空'
  if (action === 'downgraded') return '低置信度'
  if (action === 'not_generated') return '未可靠生成'
  return '已保留'
}

function isHelpfulPronunciationStatus(value: string | undefined) {
  const text = (value ?? '').trim()
  if (!text) return false
  return ![
    /未实听[，,]?\s*仅提供标准读法/,
    /未实听[，,]?\s*按字幕和常见口语规律推测/,
    /读法未可靠生成[，,]?\s*已隐藏/,
    /原句听感未可靠生成[，,]?\s*已隐藏/,
  ].some((pattern) => pattern.test(text))
}

function CardEditor({
  card,
  documentStudyMode,
  language,
  motionDuration,
  prefersReducedMotion,
  segment,
  onUpdateCard,
}: CardEditorProps) {
  const skippedEntries = Object.entries(card.skipped_card_types ?? {})
  const isKnowledgeCard = card.type === 'knowledge'
  const isReadingCard = isDocumentReadingSegment(segment, documentStudyMode)
  const cardPhraseScore = phraseValueScore(card.phrase_value_score ?? segment.phrase_value_score)
  const cardPhraseStatus = String(card.phrase_review_status ?? segmentReviewStatus(segment))
  const learningTarget = card.learning_target || card.learning_goal
  const whyItMatters = card.why_it_matters || card.why
  const howToUseIt = card.how_to_use_it || card.context
  const candidateLabel = candidateKindLabel(card.candidate_kind ?? segment.candidate_kind)
  const pronunciationMeta = normalizePronunciationMeta(card.pronunciation_meta, language)
  const standardLabel = `标准读法（${standardPronunciationHint(pronunciationMeta?.language_code ?? language)}）`
  const spokenLabel = spokenPronunciationLabel(pronunciationMeta)
  const basisHint = pronunciationBasisHint(pronunciationMeta)
  const pronunciationStatus = isHelpfulPronunciationStatus(card.pronunciation_status) ? card.pronunciation_status : ''
  const sourcePronunciationStatus = isHelpfulPronunciationStatus(card.source_pronunciation_status)
    ? card.source_pronunciation_status
    : ''
  const pronunciationFieldChanges = (pronunciationMeta?.field_changes ?? []).filter(
    (change) => change.action !== 'kept' && change.action !== 'hidden' && change.action !== 'not_generated',
  )
  const exportBlocked = cardHasExportBlockingContent(card)
  const exportable = isUsableCardForExport(segment, card)
  const cardTypeLabel =
    candidateLabel ||
    phraseTypeLabel(card.phrase_type ?? segment.phrase_type) ||
    (card.content_kind === 'vocabulary' ? '语境生词' : card.content_kind === 'grammar' ? '语法框架' : '自然表达')
  const editPointLabel = isReadingCard
    ? '精读点'
    : isKnowledgeCard
      ? '知识点'
      : cardTypeLabel === '语境生词'
        ? '语境生词'
        : '学习点'

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
            checked={card.enabled && exportable}
            disabled={!exportable}
            onChange={() => onUpdateCard(segment.id, card.id, { enabled: !card.enabled })}
          />
          <span>{card.type_label}</span>
        </label>
        <div className="card-meta-row">
          <span className={`card-export-state ${qualityClass(card)}`}>{qualityLabel(card)}</span>
          {candidateLabel ? (
            <span className={`kind-chip kind-${card.candidate_kind ?? segment.candidate_kind}`}>{candidateLabel}</span>
          ) : null}
          <span className="difficulty">{card.estimated_level ? `难度 ${card.estimated_level}` : card.difficulty}</span>
        </div>
      </div>
      {exportBlocked ? (
        <div className="card-export-blocked" role="status">
          <strong>这张卡暂不可导出</strong>
          <span>包含本地草稿、内部提示或需要人工确认的文本。请重新生成，或修正字段后再勾选导出。</span>
        </div>
      ) : !exportable ? (
        <div className="card-export-blocked" role="status">
          <strong>这张卡已过滤，不会导出</strong>
          <span>它没有通过当前质量筛选。请重新生成，或修正卡片内容后再导出。</span>
        </div>
      ) : null}
      {learningTarget || card.decision_reason || skippedEntries.length > 0 ? (
        <div className="card-plan" aria-label="卡片生成规划">
          <div>
            <span className={`role-badge ${card.card_role ?? 'primary'}`}>
              {card.card_role === 'specialist' ? '专项卡' : '主卡'}
            </span>
            {learningTarget ? <strong>{learningTarget}</strong> : null}
          </div>
          {card.decision_reason ? <p>{card.decision_reason}</p> : null}
          {card.difficulty_reason ? <p>难度判断：{card.difficulty_reason}</p> : null}
          {skippedEntries.length > 0 ? (
            <details className="skipped-card-types">
              <summary>已合并 {skippedEntries.length} 个低价值重复项</summary>
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
          <span>
            {isReadingCard
              ? '文档精读卡'
              : knowledgeTypeLabel(card.knowledge_type ?? segment.knowledge_type) || '知识卡'}
          </span>
          {learningTarget ? (
            <strong>
              {isReadingCard ? '精读动作' : '记忆动作'}：{learningTarget}
            </strong>
          ) : null}
          {whyItMatters ? (
            <p>
              {isReadingCard ? '为什么值得学' : '为什么值得记'}：{whyItMatters}
            </p>
          ) : null}
          {howToUseIt ? (
            <p>
              {isReadingCard ? '辨认 / 复用' : '适用语境'}：{howToUseIt}
            </p>
          ) : null}
          {card.quality?.issues?.length ? <p>检查提示：{card.quality.issues.join(' / ')}</p> : null}
        </div>
      ) : cardPhraseScore !== null ||
        card.phrase_decision_reason ||
        card.phrase_reject_reason ||
        card.phrase_card_focus ? (
        <div className={`phrase-card-review status-${cardPhraseStatus}`}>
          <span>
            {cardTypeLabel}
            {cardPhraseScore !== null ? ` · ${cardPhraseScore}/5` : ''}
          </span>
          {card.exact_span || segment.exact_span || card.answer_core ? (
            <p>
              {[
                card.exact_span || segment.exact_span ? `span：${card.exact_span || segment.exact_span}` : '',
                card.answer_core ? `答案：${card.answer_core}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ) : null}
          {card.phrase_card_focus ? <strong>训练点：{card.phrase_card_focus}</strong> : null}
          {card.phonetic_ipa ||
          card.spoken_ipa ||
          card.source_spoken_ipa ||
          pronunciationStatus ||
          sourcePronunciationStatus ? (
            <p>
              {[
                card.phonetic_ipa ? `${standardLabel}：${card.phonetic_ipa}` : '',
                card.spoken_ipa ? `${spokenLabel}：${card.spoken_ipa}` : '',
                card.source_spoken_ipa ? `推测原句读法：${card.source_spoken_ipa}` : '',
                pronunciationStatus ? `读法状态：${pronunciationStatus}` : '',
                sourcePronunciationStatus ? `推测原句读法状态：${sourcePronunciationStatus}` : '',
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          ) : null}
          {basisHint ? <p>置信提示：{basisHint}</p> : null}
          {pronunciationFieldChanges.length ? (
            <div className="pronunciation-field-changes" aria-label="发音字段变更">
              {pronunciationFieldChanges.map((change) => (
                <span key={`${change.field}-${change.action}-${change.code}`}>
                  {pronunciationFieldLabel(change.field)}：{pronunciationActionLabel(change.action)}
                  {change.message ? ` · ${change.message}` : ''}
                </span>
              ))}
            </div>
          ) : null}
          {card.pronunciation_note ? <p>听点：{card.pronunciation_note}</p> : null}
          {whyItMatters ? <p>为什么值得学：{whyItMatters}</p> : null}
          {howToUseIt ? <p>怎么用：{howToUseIt}</p> : null}
          {card.phrase_decision_reason ? <p>筛选理由：{card.phrase_decision_reason}</p> : null}
          {card.phrase_reject_reason ? <p>检查提示：{card.phrase_reject_reason}</p> : null}
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
          {editPointLabel}
          <textarea
            value={card.phrase}
            onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
              onUpdateCard(segment.id, card.id, { phrase: event.target.value })
            }
          />
        </label>
        {!isKnowledgeCard ? (
          <>
            <label>
              {standardLabel}
              <textarea
                value={card.phonetic_ipa ?? ''}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                  onUpdateCard(segment.id, card.id, { phonetic_ipa: event.target.value })
                }
              />
            </label>
            <label>
              {spokenLabel}
              <textarea
                value={card.spoken_ipa ?? ''}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                  onUpdateCard(segment.id, card.id, { spoken_ipa: event.target.value })
                }
              />
            </label>
            <label>
              推测原句读法 / 发音提示
              <textarea
                value={[card.source_spoken_ipa ?? '', card.pronunciation_note ?? ''].filter(Boolean).join('\n')}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => {
                  const [source_spoken_ipa, ...rest] = event.target.value.split('\n')
                  onUpdateCard(segment.id, card.id, {
                    source_spoken_ipa,
                    pronunciation_note: rest.join('\n'),
                  })
                }}
              />
            </label>
          </>
        ) : null}
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
