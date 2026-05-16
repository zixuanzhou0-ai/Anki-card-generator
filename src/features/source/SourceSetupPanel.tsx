import { FileText, Film, FolderOpen, Link2, Subtitles } from 'lucide-react'

import type { GenerateRequest, SourceMode } from '../../domain/types'

type SourceSetupPanelProps = {
  request: GenerateRequest
  onPatchRequest: (patch: Partial<GenerateRequest>) => void
  onSelectPath: (kind: 'video' | 'subtitle' | 'document') => void
  onSelectSourceMode: (mode: SourceMode) => void
}

export function SourceSetupPanel({
  request,
  onPatchRequest,
  onSelectPath,
  onSelectSourceMode,
}: SourceSetupPanelProps) {
  const sourceLabel =
    request.source_mode === 'url' ? '视频链接' : request.source_mode === 'document' ? '文档资料' : '本地视频'

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
          <span>项目标题</span>
          <input
            value={request.title}
            onChange={(event) => onPatchRequest({ title: event.target.value })}
            placeholder="例如 Friends S01E01"
          />
        </label>
        {request.source_mode === 'url' ? (
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
            <p className="document-source-hint">文档目标、讲解语言和吸收深度在下方“文档目标”里调整。</p>
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
                onChange={() =>
                  onPatchRequest({ url_auto_subtitle_fallback: !request.url_auto_subtitle_fallback })
                }
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
      ) : null}
    </div>
  )
}
