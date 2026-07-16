import type { WorkflowIssue } from './workflowState'

export type WorkflowIssueResolution =
  | 'check_environment'
  | 'repair_environment'
  | 'test_api'
  | 'open_api_settings'
  | 'test_tts'
  | 'open_tts_settings'
  | 'navigate_source'
  | 'navigate_select'
  | 'none'

const API_TEST_LABELS = new Set(['验证模型', '重新验证', '启动代理'])
const TTS_TEST_LABELS = new Set(['验证语音', '重新验证'])
const ENVIRONMENT_CHECK_LABELS = new Set(['检查环境', '重新检查'])

/**
 * Resolve the single user-facing recovery action without coupling the UI to
 * capability state or opening settings as a catch-all side effect.
 */
export function resolutionForWorkflowIssue(issue: WorkflowIssue | undefined): WorkflowIssueResolution {
  if (!issue) return 'none'

  switch (issue.id) {
    case 'environment':
      if (!issue.resolutionLabel) return 'none'
      return ENVIRONMENT_CHECK_LABELS.has(issue.resolutionLabel) ? 'check_environment' : 'repair_environment'
    case 'api':
      return issue.resolutionLabel && API_TEST_LABELS.has(issue.resolutionLabel) ? 'test_api' : 'open_api_settings'
    case 'tts':
      return issue.resolutionLabel && TTS_TEST_LABELS.has(issue.resolutionLabel) ? 'test_tts' : 'open_tts_settings'
    case 'source_missing':
    case 'learning_points_missing':
      return 'navigate_source'
    case 'selection_empty':
      return 'navigate_select'
    default:
      return 'none'
  }
}
