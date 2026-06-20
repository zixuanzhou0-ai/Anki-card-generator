import { Film, FolderOpen, Link2, Subtitles } from 'lucide-react'

import { batchItemsForSource, buildBatchPackage, createUrlBatchItems } from '../../domain/batch'
import { publicSourceModeFor, type PublicSourceMode } from '../../domain/publicSource'
import type { GenerateRequest, SourceMode } from '../../domain/types'

type SourcePathKind = 'video' | 'subtitle' | 'video-folder'

type SourceSetupPanelProps = {
  request: GenerateRequest
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectPath: (kind: SourcePathKind) => void
  onSelectSourceMode: (mode: SourceMode) => void
}

function sourceLabelFor(mode: PublicSourceMode, batchEnabled: boolean) {
  if (batchEnabled) {
    return mode === 'url' ? '批量视频链接' : '批量视频文件夹'
  }
  return mode === 'url' ? '视频链接' : '本地视频'
}

function sourceItemText(item: { video_path?: string; subtitle_path?: string; source_url?: string; document_path?: string }) {
  return item.video_path || item.source_url || item.document_path || ''
}

function batchSourceHint(mode: PublicSourceMode) {
  if (mode === 'url') return '每行一个链接，适合课程列表、播放列表或一组短视频。'
  return '选择剧集或课程文件夹，系统会自动按文件名排序并匹配同目录字幕。'
}

function BatchPackagePreview({ count, mode, title }: { count: number; mode: PublicSourceMode; title: string }) {
  return (
    <section className="batch-package-preview" aria-label="批量学习包预览">
      <div className="batch-package-title">
        <span>学习包结构</span>
        <strong>学习包：{title}</strong>
        <small>一个 APKG · {count} 个嵌套子牌组</small>
      </div>
      <ol className="batch-flow-steps" aria-label="批量制卡步骤">
        <li>
          <strong>先添加素材</strong>
          <small>{batchSourceHint(mode)}</small>
        </li>
        <li>
          <strong>确认子牌组</strong>
          <small>每个视频或链接都会成为 Anki 里的一个子卡包。</small>
        </li>
        <li>
          <strong>统一生成导出</strong>
          <small>一次生成一个 APKG，导入后仍保留学习包层级。</small>
        </li>
      </ol>
    </section>
  )
}

function BatchItemList({ items }: { items: ReturnType<typeof batchItemsForSource> }) {
  if (!items.length) {
    return <p className="document-source-hint">还没有批量素材。选择视频文件夹或粘贴多个链接后会在这里确认子卡包。</p>
  }
  return (
    <div className="batch-item-list" aria-label="批量素材列表">
      {items.map((item) => (
        <article className="batch-item-row" key={item.id}>
          <strong>{item.subdeck_title}</strong>
          {item.deck_name ? <small className="batch-deck-path">{item.deck_name}</small> : null}
          <small>{sourceItemText(item)}</small>
          {item.subtitle_path ? <small>字幕：{item.subtitle_path}</small> : null}
          {item.warning ? <small className="warning-copy">{item.warning}</small> : null}
        </article>
      ))}
    </div>
  )
}

export function SourceSetupPanel({ request, onPatchRequest, onSelectPath, onSelectSourceMode }: SourceSetupPanelProps) {
  const sourceMode = publicSourceModeFor(request.source_mode)
  const sourceLabel = sourceLabelFor(sourceMode, request.batch_enabled)
  const batchItems = batchItemsForSource(request.batch_items ?? [], sourceMode)
  const batchCount = batchItems.length
  const batchTitle = request.title.trim() || '无标题学习包'

  const addUrlBatchItems = () => {
    const nextItems = createUrlBatchItems(request.source_url)
    const existingOtherSources = (request.batch_items ?? []).filter((item) => item.source_mode !== 'url')
    const existingUrlKeys = new Set<string>()
    const mergedUrls = [...batchItems, ...nextItems].filter((item) => {
      const key = item.source_url || item.id
      if (existingUrlKeys.has(key)) return false
      existingUrlKeys.add(key)
      return true
    })
    const title = request.title.trim() || '视频链接学习包'
    const batchPackage = buildBatchPackage({ title, source_mode: 'url', items: mergedUrls })
    onPatchRequest({ title, batch_enabled: true, batch_items: [...existingOtherSources, ...batchPackage.items] })
  }

  return (
    <div className="panel source-panel">
      <div className="panel-heading">
        <FolderOpen size={20} />
        <h3>素材</h3>
      </div>
      <div className="source-switch" aria-label="素材来源">
        <button
          type="button"
          className={sourceMode === 'local' ? 'selected' : ''}
          aria-pressed={sourceMode === 'local'}
          onClick={() => onSelectSourceMode('local')}
        >
          <Film size={18} />
          <span>本地视频</span>
          <small>视频 + SRT</small>
        </button>
        <button
          type="button"
          className={sourceMode === 'url' ? 'selected' : ''}
          aria-pressed={sourceMode === 'url'}
          onClick={() => onSelectSourceMode('url')}
        >
          <Link2 size={18} />
          <span>视频链接</span>
          <small>YouTube / URL</small>
        </button>
      </div>
      <details className="compact-details source-input-details" open>
        <summary>
          <span>输入内容</span>
          <strong>{sourceLabel}</strong>
        </summary>
        <label className="field project-title-field">
          <span>{request.batch_enabled ? '学习包标题' : '项目标题'}</span>
          <input
            value={request.title}
            onChange={(event) => onPatchRequest({ title: event.target.value })}
            placeholder={request.batch_enabled ? '例如 无耻之徒 第一季' : '例如 Friends S01E01'}
          />
        </label>
        <div className="segmented compact-segmented" aria-label="添加方式">
          <button type="button" className={!request.batch_enabled ? 'selected' : ''} onClick={() => onPatchRequest({ batch_enabled: false })}>
            单个素材
          </button>
          <button type="button" className={request.batch_enabled ? 'selected' : ''} onClick={() => onPatchRequest({ batch_enabled: true })}>
            批量 / 文件夹
          </button>
        </div>
        {request.batch_enabled ? (
          <div className="batch-source-panel">
            <div className="batch-source-header">
              <div>
                <strong>{sourceMode === 'url' ? '批量链接列表' : '批量视频列表'}</strong>
                <small>已添加 {batchCount} 个素材</small>
              </div>
              <button type="button" className="ghost-button" onClick={() => onPatchRequest({ batch_enabled: false })} aria-label="关闭批量模式">
                关闭批量模式
              </button>
            </div>
            <BatchItemList items={batchItems} />
            {sourceMode === 'url' ? (
              <label className="field">
                <span>每行一个视频链接</span>
                <textarea
                  value={request.source_url}
                  onChange={(event) => onPatchRequest({ source_url: event.target.value })}
                  placeholder={'https://www.youtube.com/watch?v=...\nhttps://youtu.be/...'}
                  rows={5}
                />
                <button type="button" className="secondary-button" onClick={addUrlBatchItems}>
                  添加链接到批量列表
                </button>
              </label>
            ) : (
              <button type="button" className="secondary-button" onClick={() => onSelectPath('video-folder')} aria-label="选择视频文件夹批量添加">
                <Film size={18} />
                选择视频文件夹批量添加
              </button>
            )}
            <BatchPackagePreview count={batchCount} mode={sourceMode} title={batchTitle} />
          </div>
        ) : sourceMode === 'url' ? (
          <label className="field">
            <span>YouTube / 视频 URL</span>
            <input
              value={request.source_url}
              onChange={(event) => onPatchRequest({ source_url: event.target.value })}
              placeholder="https://www.youtube.com/watch?v=..."
            />
            <small>当前发布版会按视频制卡处理：下载视频和字幕，并在导出时生成视频片段、原声和 TTS。</small>
          </label>
        ) : (
          <>
            <label className="field file-field">
              <span>视频文件</span>
              <div>
                <input
                  value={request.video_path}
                  onChange={(event) => onPatchRequest({ video_path: event.target.value, local_path_access_confirmed: false })}
                  placeholder="选择本地视频"
                />
                <button type="button" onClick={() => onSelectPath('video')} aria-label="选择视频文件">
                  <Film size={18} />
                </button>
              </div>
            </label>
            <label className="field file-field">
              <span>SRT 字幕</span>
              <div>
                <input
                  value={request.subtitle_path}
                  onChange={(event) => onPatchRequest({ subtitle_path: event.target.value, local_path_access_confirmed: false })}
                  placeholder="选择 SRT 字幕"
                />
                <button type="button" onClick={() => onSelectPath('subtitle')} aria-label="选择字幕文件">
                  <Subtitles size={18} />
                </button>
              </div>
              <small>可留空；生成时会自动匹配同目录 SRT/VTT，也会尝试提取 MKV/MP4 内嵌文字字幕。</small>
            </label>
          </>
        )}
      </details>
    </div>
  )
}
