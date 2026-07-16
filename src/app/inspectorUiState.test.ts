import { describe, expect, it } from 'vitest'

import { buildInspectorUiState } from './inspectorUiState'

describe('inspectorUiState', () => {
  it('uses sheet labels on compact layouts', () => {
    expect(
      buildInspectorUiState({
        responsiveMode: 'compact',
        inspectorState: 'open',
        prefersReducedMotion: false,
      }),
    ).toMatchObject({
      inspectorSheetOpen: false,
      inspectorActionLabel: '流程',
      motionDuration: 0.2,
    })

    expect(
      buildInspectorUiState({
        responsiveMode: 'compact',
        inspectorState: 'sheet',
        prefersReducedMotion: false,
      }),
    ).toMatchObject({
      inspectorSheetOpen: true,
      inspectorActionLabel: '关闭流程',
    })
  })

  it('uses collapse labels on wide and medium layouts', () => {
    expect(
      buildInspectorUiState({
        responsiveMode: 'wide',
        inspectorState: 'collapsed',
        prefersReducedMotion: false,
      }).inspectorActionLabel,
    ).toBe('展开流程')

    expect(
      buildInspectorUiState({
        responsiveMode: 'medium',
        inspectorState: 'open',
        prefersReducedMotion: false,
      }).inspectorActionLabel,
    ).toBe('收起流程')
  })

  it('disables motion duration when reduced motion is preferred', () => {
    expect(
      buildInspectorUiState({
        responsiveMode: 'wide',
        inspectorState: 'collapsing',
        prefersReducedMotion: true,
      }).motionDuration,
    ).toBe(0)
  })
})
