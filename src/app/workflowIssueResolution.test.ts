import { describe, expect, it } from 'vitest'

import type { WorkflowIssue } from './workflowState'
import { resolutionForWorkflowIssue } from './workflowIssueResolution'

function issue(id: string, resolutionLabel?: string): WorkflowIssue {
  return {
    id,
    severity: 'blocker',
    action: 'resolve_blocker',
    title: id,
    detail: id,
    resolutionLabel,
  }
}

describe('resolutionForWorkflowIssue', () => {
  it.each([
    ['验证模型', 'test_api'],
    ['重新验证', 'test_api'],
    ['启动代理', 'test_api'],
    ['配置授权', 'open_api_settings'],
    ['修复模型', 'open_api_settings'],
    ['配置模型', 'open_api_settings'],
  ] as const)('maps model action %s to %s', (label, expected) => {
    expect(resolutionForWorkflowIssue(issue('api', label))).toBe(expected)
  })

  it.each([
    ['验证语音', 'test_tts'],
    ['重新验证', 'test_tts'],
    ['配置授权', 'open_tts_settings'],
    ['修复语音', 'open_tts_settings'],
    ['启用语音', 'open_tts_settings'],
  ] as const)('maps TTS action %s to %s', (label, expected) => {
    expect(resolutionForWorkflowIssue(issue('tts', label))).toBe(expected)
  })

  it.each([
    ['检查环境', 'check_environment'],
    ['重新检查', 'check_environment'],
    ['修复环境', 'repair_environment'],
    ['查看修复方法', 'repair_environment'],
  ] as const)('maps environment action %s to %s', (label, expected) => {
    expect(resolutionForWorkflowIssue(issue('environment', label))).toBe(expected)
  })

  it('does nothing while a capability check has no available recovery action', () => {
    expect(resolutionForWorkflowIssue(issue('environment'))).toBe('none')
  })

  it.each([
    ['source_missing', 'navigate_source'],
    ['learning_points_missing', 'navigate_source'],
    ['selection_empty', 'navigate_select'],
    ['exportable_cards_missing', 'none'],
  ] as const)('maps structural issue %s to %s', (id, expected) => {
    expect(resolutionForWorkflowIssue(issue(id, '修复'))).toBe(expected)
  })

  it('does nothing when there is no issue', () => {
    expect(resolutionForWorkflowIssue(undefined)).toBe('none')
  })
})
