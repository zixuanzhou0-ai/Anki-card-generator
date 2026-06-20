import type { Project, SourceMode } from './types'

export type PublicSourceMode = Exclude<SourceMode, 'document'>

export type PublicProjectSourceStatus = {
  publicSourceMode: PublicSourceMode
  isPublicVideoProject: boolean
  isHistoricalNonPublicProject: boolean
  notice: string
}

export function publicSourceModeFor(sourceMode: SourceMode | undefined): PublicSourceMode {
  return sourceMode === 'url' ? 'url' : 'local'
}

export function publicProjectSourceStatus(project: Pick<Project, 'source_mode'> | null): PublicProjectSourceStatus {
  const mode = project?.source_mode
  const isHistoricalNonPublicProject = mode === 'document'
  return {
    publicSourceMode: publicSourceModeFor(mode),
    isPublicVideoProject: !isHistoricalNonPublicProject,
    isHistoricalNonPublicProject,
    notice: isHistoricalNonPublicProject
      ? '当前发布版只支持本地视频和视频链接；这个历史项目不会作为普通制卡入口。请重新选择视频素材。'
      : '',
  }
}
