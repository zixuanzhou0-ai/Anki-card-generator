import { afterEach, describe, expect, it } from 'vitest'

import {
  appModalActive,
  deliveryFooterSummary,
  existingArtifactDestination,
  modalBackgroundAttributes,
  resetWorkflowStepViewport,
  sourcePrimaryTarget,
} from './AppShell'

afterEach(() => {
  document.body.replaceChildren()
})

describe('modalBackgroundAttributes', () => {
  it('makes modal background inert and restores normal attributes when the modal closes', () => {
    expect(modalBackgroundAttributes(true)).toEqual({ 'aria-hidden': true, inert: true })
    expect(modalBackgroundAttributes(false)).toEqual({})
  })
})

describe('appModalActive', () => {
  it('treats the generation confirmation as a real app modal', () => {
    expect(appModalActive(false, false, true)).toBe(true)
    expect(appModalActive(true, false, false)).toBe(true)
    expect(appModalActive(false, true, false)).toBe(true)
    expect(appModalActive(false, false, false)).toBe(false)
  })
})
describe('resetWorkflowStepViewport', () => {
  it('resets outgoing and target scroll positions before focusing the target title', () => {
    const outgoing = document.createElement('div')
    outgoing.className = 'source-workspace-content'
    outgoing.scrollTop = 240

    const target = document.createElement('div')
    target.className = 'workflow-step-scroll'
    target.scrollTop = 360
    const heading = document.createElement('h1')
    heading.dataset.workflowPageTitle = 'true'
    heading.tabIndex = -1
    let scrollAtFocus: [number, number] | null = null
    heading.addEventListener('focus', () => {
      scrollAtFocus = [outgoing.scrollTop, target.scrollTop]
    })
    document.body.append(target, heading)

    resetWorkflowStepViewport([outgoing])

    expect(outgoing.scrollTop).toBe(0)
    expect(target.scrollTop).toBe(0)
    expect(scrollAtFocus).toEqual([0, 0])
    expect(document.activeElement).toBe(heading)
  })
})
describe('existingArtifactDestination', () => {
  it.each([
    ['empty', null],
    ['source_ready', null],
    ['learning_points_ready', 'select'],
    ['drafts_ready', 'deliver'],
    ['apkg_ready', 'deliver'],
    ['anki_verified', 'deliver'],
  ] as const)('routes %s to %s', (artifactStage, expected) => {
    expect(existingArtifactDestination(artifactStage)).toBe(expected)
  })

  it.each([
    ['empty', 'extract_learning_points'],
    ['source_ready', 'extract_learning_points'],
    ['learning_points_ready', 'select'],
    ['drafts_ready', 'deliver'],
    ['apkg_ready', 'deliver'],
    ['anki_verified', 'deliver'],
  ] as const)('maps the source primary action for %s to %s', (artifactStage, expected) => {
    expect(sourcePrimaryTarget(artifactStage)).toBe(expected)
  })
})

describe('deliveryFooterSummary', () => {
  it.each([
    ['drafts_ready', '9 张可安全导出'],
    ['apkg_ready', 'APKG 已生成，尚未导入 Anki'],
    ['anki_verified', '已在 Anki 中核验'],
  ] as const)('uses artifact-specific copy for %s', (artifactStage, expected) => {
    expect(deliveryFooterSummary(artifactStage, 9).title).toBe(expected)
  })
})
