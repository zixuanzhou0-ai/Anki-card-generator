import { FileText, Film, FolderOpen, Link2, Subtitles } from 'lucide-react'

import { batchItemsForSource, buildBatchPackage, createUrlBatchItems } from '../../domain/batch'
import type { GenerateRequest, SourceMode } from '../../domain/types'

type SourcePathKind = 'video' | 'subtitle' | 'document' | 'video-folder' | 'document-folder'

type SourceSetupPanelProps = {
  request: GenerateRequest
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectPath: (kind: SourcePathKind) => void
  onSelectSourceMode: (mode: SourceMode) => void
}

function sourceLabelFor(mode: SourceMode, batchEnabled: boolean) {
  if (batchEnabled) {
    return mode === 'url' ? '批量视频链接' : mode === 'document' ? '批量文档 / 文件夹' : '批量视频文件夹'
  }
  return mode === 'url' ? '视频链接' : mode === 'document' ? '文档资料' : '本地视频'
}

function sourceItemText(item: { video_path?: string; subtitle_path?: string; source_url?: string; document_path?: string }) {
  return item.video_path || item.source_url || item.document_path || ''
}

function batchSourceHint(mode: SourceMode) {
  if (mode === 'url') return '每行一个链接，适合课程列表、播放列表或一组短视频。'
  if (mode === 'document') return '选择一个资料文件夹，系统会把每份文档整理成独立子牌组。'
  return '选择剧集或课程文件夹，系统会自动按文件名排序并匹配同目录字幕。'
}

function BatchPackagePreview({ count, mode, title }: { count: number; mode: SourceMode; title: string }) {
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
          <small>每个视频、链接或文档都会成为 Anki 里的一个子卡包。</small>
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
    return <p className="document-source-hint">还没有批量素材。选择文件夹、粘贴多个链接，或添加一组文档后会在这里确认子卡包。</p>
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
  const sourceLabel = sourceLabelFor(request.source_mode, request.batch_enabled)
  const batchItems = batchItemsForSource(request.batch_items ?? [], request.source_mode)
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
          className={request.source_mode === 'local' ? 'selected' : ''}
          aria-pressed={request.source_mode === 'local'}
          onClick={() => onSelectSourceMode('local')}
        >
          <Film size={18} />
          <span>本地视频</span>
          <small>视频 + SRT</small>
        </button>
        <button
          type="button"
          className={request.source_mode === 'url' ? 'selected' : ''}
          aria-pressed={request.source_mode === 'url'}
          onClick={() => onSelectSourceMode('url')}
        >
          <Link2 size={18} />
          <span>视频链接</span>
          <small>YouTube / URL</small>
        </button>
        <button
          type="button"
          className={request.source_mode === 'document' ? 'selected' : ''}
          aria-pressed={request.source_mode === 'document'}
          onClick={() => onSelectSourceMode('document')}
        >
          <FileText size={18} />
          <span>文档资料</span>
          <small>PDF / Word / EPUB</small>
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
                <strong>{request.source_mode === 'url' ? '批量链接列表' : request.source_mode === 'document' ? '批量文档列表' : '批量视频列表'}</strong>
                <small>已添加 {batchCount} 个素材</small>
              </div>
              <button type="button" className="ghost-button" onClick={() => onPatchRequest({ batch_enabled: false })} aria-label="关闭批量模式">
                关闭批量模式
              </button>
            </div>
            <BatchItemList items={batchItems} />
            {request.source_mode === 'url' ? (
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
            ) : request.source_mode === 'document' ? (
              <button type="button" className="secondary-button" onClick={() => onSelectPath('document-folder')} aria-label="选择文档文件夹批量添加">
                <FileText size={18} />
                选择文档文件夹批量添加
              </button>
            ) : (
              <button type="button" className="secondary-button" onClick={() => onSelectPath('video-folder')} aria-label="选择视频文件夹批量添加">
                <Film size={18} />
                选择视频文件夹批量添加
              </button>
            )}
            <BatchPackagePreview count={batchCount} mode={request.source_mode} title={batchTitle} />
          </div>
        ) : request.source_mode === 'url' ? (
          <label className="field">
            <span>YouTube / 视频 URL</span>
            <input
              value={request.source_url}
              onChange={(event) => onPatchRequest({ source_url: event.target.value })}
              placeholder="https://www.youtube.com/watch?v=..."
            />
            <small>失败时可切到字幕-only 或手动上传 SRT 继续制卡。</small>
          </label>
        ) : request.source_mode === 'document' ? (
          <>
            <label className="field file-field">
              <span>文档资料</span>
              <div>
                <input
                  value={request.document_path}
                  onChange={(event) => onPatchRequest({ document_path: event.target.value })}
                  placeholder="选择文档资料"
                />
                <button type="button" onClick={() => onSelectPath('document')} aria-label="选择文档资料">
                  <FileText size={18} />
                </button>
              </div>
              <small>支持 TXT、Markdown、DOCX、EPUB、PDF。扫描版 PDF 需要后续 OCR。</small>
            </label>
            <div className="document-source-flow" aria-label="文档制卡流程">
              <span>上传资料</span>
              <span>选择目标</span>
              <span>生成知识卡</span>
            </div>
            <p className="document-source-hint">上传后只需调整文档目标，系统会自动拆知识点，不需要字幕、切片或 TTS。</p>
          </>
        ) : (
          <>
            <label className="field file-field">
              <span>视频文件</span>
              <div>
                <input
                  value={request.video_path}
                  onChange={(event) => onPatchRequest({ video_path: event.target.value })}
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
                  onChange={(event) => onPatchRequest({ subtitle_path: event.target.value })}
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
      {request.source_mode === 'url' ? (
        <details className="compact-details inspector-fold url-options-details">
          <summary>
            <span>下载和 fallback</span>
            <strong>{request.url_import_mode === 'subtitles' ? '字幕-only' : '视频+字幕'}</strong>
          </summary>
          <div className="url-fallback-options" aria-label="URL 导入 fallback">
            <div className="segmented compact-segmented">
              <button
                type="button"
                className={request.url_import_mode === 'video' ? 'selected' : ''}
                onClick={() => onPatchRequest({ url_import_mode: 'video', skip_video_slicing: false })}
              >
                下载视频+字幕
              </button>
              <button
                type="button"
                className={request.url_import_mode === 'subtitles' ? 'selected' : ''}
                onClick={() => onPatchRequest({ url_import_mode: 'subtitles', skip_video_slicing: true })}
              >
                只用字幕生成
              </button>
            </div>
            <label className="toggle">
              <input
                type="checkbox"
                checked={request.url_auto_subtitle_fallback}
                onChange={() => onPatchRequest({ url_auto_subtitle_fallback: !request.url_auto_subtitle_fallback })}
              />
              <span>视频下载失败时自动 fallback 到字幕-only</span>
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={request.skip_video_slicing}
                onChange={() => {
                  const next = !request.skip_video_slicing
                  onPatchRequest({
                    skip_video_slicing: next,
                    url_import_mode: next ? 'subtitles' : request.url_import_mode,
                  })
                }}
              />
              <span>导出时跳过视频切片，只保留字幕和 TTS</span>
            </label>
          </div>
        </details>
      ) : request.source_mode === 'local' ? (
        <details className="compact-details inspector-fold local-options-details" open>
          <summary>
            <span>导出方式</span>
            <strong>{request.skip_video_slicing ? '字幕-only' : '视频切片'}</strong>
          </summary>
          <div className="url-fallback-options" aria-label="本地视频导出方式">
            <label className="toggle">
              <input
                type="checkbox"
                checked={request.skip_video_slicing}
                onChange={() => onPatchRequest({ skip_video_slicing: !request.skip_video_slicing })}
              />
              <span>导出时跳过视频切片，只保留字幕和 TTS</span>
            </label>
            <p className="document-source-hint">视频过大、切片很慢或媒体失败时，可先用字幕-only 产出可复习卡。</p>
          </div>
        </details>
      ) : null}
    </div>
  )
}
