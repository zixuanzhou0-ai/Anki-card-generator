import type { ReliabilityManifest } from '../../domain/types'

type ReliabilitySummaryPanelProps = {
  manifest?: ReliabilityManifest
}

function verificationProfileLabel(profile: string) {
  if (profile === 'structural_v1') return 'structural_v1（结构级）'
  return profile
}

export function ReliabilitySummaryPanel({ manifest }: ReliabilitySummaryPanelProps) {
  if (!manifest) return null

  const structuralOnly = manifest.verification_profile === 'structural_v1'

  return (
    <div
      className={'review-export-summary reliability-summary reliability-' + manifest.decision}
      role="status"
      aria-label="制卡可靠性门禁"
    >
      <div className="export-count-card">
        <span>制卡可靠性门禁</span>
        <div>
          <strong>{manifest.verified_count}</strong>
          <em>{'/ ' + manifest.selected_point_count + ' 个选点已通过'}</em>
        </div>
        <small>
          {manifest.decision === 'pass'
            ? structuralOnly
              ? '已通过结构、来源与导出门禁；这不等同于独立语义校对。'
              : '全部选点已通过当前可靠性检查，可以进入导出准备。'
            : '可靠性门禁已阻断：待复核或硬失败选点处理完成前，不会生成正式 APKG。'}
          {' 检查档案：' + verificationProfileLabel(manifest.verification_profile) + '。'}
        </small>
      </div>
      <div className="export-side-metrics">
        <span>
          <strong>{manifest.verified_count}</strong>
          <small>{structuralOnly ? '结构通过' : '已验证'}</small>
        </span>
        <span>
          <strong>{manifest.needs_review_count}</strong>
          <small>待复核</small>
        </span>
        <span>
          <strong>{manifest.hard_failed_count}</strong>
          <small>硬失败</small>
        </span>
      </div>
    </div>
  )
}
