import type { InspectorState, ResponsiveMode } from '../domain/types'

export type InspectorUiState = {
  inspectorSheetOpen: boolean
  inspectorActionLabel: string
  motionDuration: number
}

export function buildInspectorUiState({
  responsiveMode,
  inspectorState,
  prefersReducedMotion,
}: {
  responsiveMode: ResponsiveMode
  inspectorState: InspectorState
  prefersReducedMotion: boolean | null
}): InspectorUiState {
  const inspectorSheetOpen = responsiveMode === 'compact' && inspectorState === 'sheet'
  const inspectorActionLabel =
    responsiveMode === 'compact'
      ? inspectorSheetOpen
        ? '关闭流程'
        : '流程'
      : inspectorState === 'collapsed'
        ? '展开流程'
        : '收起流程'

  return {
    inspectorSheetOpen,
    inspectorActionLabel,
    motionDuration: prefersReducedMotion ? 0 : 0.2,
  }
}
