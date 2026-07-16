import { CheckCircle2, CircleDot, FileVideo2, Layers3, PackageCheck } from 'lucide-react'

import type { ProductStep, WorkflowUiSnapshot } from '../../app/workflowState'
import { batchItemsForSource } from '../../domain/batch'
import { publicSourceModeFor } from '../../domain/publicSource'
import type { GenerateRequest } from '../../domain/types'

type WorkflowRailProps = {
  snapshot: WorkflowUiSnapshot
  request: GenerateRequest
  learningPointCount?: number
  draftCardCount?: number
  onStepChange: (step: ProductStep) => void
}

const ARTIFACT_ORDER: Record<WorkflowUiSnapshot['artifactStage'], number> = {
  empty: 0,
  source_ready: 1,
  learning_points_ready: 2,
  drafts_ready: 3,
  apkg_ready: 4,
  anki_verified: 5,
}

const STEPS = [
  { id: 'source', label: '添加素材', icon: FileVideo2 },
  { id: 'select', label: '选择学习点', icon: Layers3 },
  { id: 'deliver', label: '生成并导入', icon: PackageCheck },
] as const

export function WorkflowRail({
  snapshot,
  request,
  learningPointCount = 0,
  draftCardCount = 0,
  onStepChange,
}: WorkflowRailProps) {
  const artifactRank = ARTIFACT_ORDER[snapshot.artifactStage]
  const sourceSummary = summarizeSource(request)

  const canEnterStep = (step: ProductStep) => {
    if (step === 'source') return true
    if (step === snapshot.step) return true
    if (step === 'select') return artifactRank >= ARTIFACT_ORDER.learning_points_ready
    return artifactRank >= ARTIFACT_ORDER.drafts_ready
  }

  const statusFor = (step: ProductStep) => {
    if (step === 'source') return artifactRank >= ARTIFACT_ORDER.source_ready ? '素材已就绪' : '等待添加素材'
    if (step === 'select') {
      return artifactRank >= ARTIFACT_ORDER.learning_points_ready
        ? `${String(Math.max(0, learningPointCount))} 个可靠学习点`
        : '分析后可选择'
    }
    if (snapshot.artifactStage === 'anki_verified') return '已在 Anki 中核验'
    if (snapshot.artifactStage === 'apkg_ready') return 'APKG 已生成'
    if (artifactRank >= ARTIFACT_ORDER.drafts_ready) return `${String(Math.max(0, draftCardCount))} 张卡片草稿`
    return '选择后生成'
  }

  return (
    <aside className="workflow-rail" aria-label="制卡流程导航">
      <div className="workflow-rail-heading">
        <span>制卡流程</span>
        <strong>第 {STEPS.findIndex((step) => step.id === snapshot.step) + 1}/3 步</strong>
      </div>

      <nav aria-label="三步制卡流程">
        <ol className="workflow-rail-steps">
          {STEPS.map((step, index) => {
            const selected = step.id === snapshot.step
            const available = canEnterStep(step.id)
            const completed = isStepComplete(step.id, artifactRank)
            const Icon = step.icon

            return (
              <li key={step.id} className={selected ? 'selected' : completed ? 'complete' : ''}>
                <button
                  type="button"
                  className="workflow-rail-step"
                  aria-current={selected ? 'step' : undefined}
                  disabled={!available}
                  onClick={() => onStepChange(step.id)}
                >
                  <span className="workflow-rail-index" aria-hidden="true">
                    {index + 1}
                  </span>
                  <Icon size={18} aria-hidden="true" />
                  <span className="workflow-rail-copy">
                    <strong>{step.label}</strong>
                    <small>{available ? statusFor(step.id) : '先完成上一步'}</small>
                  </span>
                  {completed ? (
                    <CheckCircle2 className="workflow-rail-state complete" size={18} aria-label="已完成" />
                  ) : selected ? (
                    <CircleDot className="workflow-rail-state current" size={18} aria-label="当前步骤" />
                  ) : null}
                </button>
              </li>
            )
          })}
        </ol>
      </nav>

      <section className="workflow-rail-source-summary" aria-label="当前素材摘要">
        <span>当前素材</span>
        <strong>{sourceSummary.title}</strong>
        <small>{sourceSummary.detail}</small>
      </section>
    </aside>
  )
}

function isStepComplete(step: ProductStep, artifactRank: number): boolean {
  if (step === 'source') return artifactRank >= ARTIFACT_ORDER.source_ready
  if (step === 'select') return artifactRank >= ARTIFACT_ORDER.learning_points_ready
  return artifactRank >= ARTIFACT_ORDER.anki_verified
}

function summarizeSource(request: GenerateRequest): { title: string; detail: string } {
  const sourceMode = publicSourceModeFor(request.source_mode)

  if (request.batch_enabled) {
    const count = batchItemsForSource(request.batch_items ?? [], sourceMode).length
    return {
      title: request.title.trim() || '未命名学习包',
      detail: count > 0 ? `${String(count)} 个素材` : '尚未添加批量素材',
    }
  }

  if (sourceMode === 'url') {
    return {
      title: request.title.trim() || '视频链接',
      detail: request.source_url.trim() ? '链接已填写' : '尚未填写链接',
    }
  }

  return {
    title: request.title.trim() || '本地视频',
    detail: request.video_path.trim() ? fileNameFor(request.video_path) : '尚未选择视频',
  }
}

function fileNameFor(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? path
}
