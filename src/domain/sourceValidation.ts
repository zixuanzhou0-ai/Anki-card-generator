import { batchItemsForSource } from './batch'
import type { GenerateRequest } from './types'

const videoExtensions = new Set(['.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'])

function cleanPath(value: string | undefined) {
  return (value ?? '').trim().replace(/^["'](.+)["']$/, '$1')
}

function extensionOf(value: string | undefined) {
  const cleaned = cleanPath(value).replace(/\\/g, '/')
  const name = cleaned.split('/').filter(Boolean).pop() ?? cleaned
  const match = name.match(/\.[^.]+$/u)
  return match ? match[0].toLowerCase() : ''
}

export function isHttpVideoUrl(value: string | undefined) {
  const cleaned = (value ?? '').trim()
  if (!cleaned) return false
  try {
    const url = new URL(cleaned)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

export function isSupportedVideoPath(value: string | undefined) {
  return videoExtensions.has(extensionOf(value))
}

export function isSupportedDocumentPath(_value: string | undefined) {
  return false
}

export function isSourceInputReady(request: GenerateRequest) {
  if (request.source_mode === 'document') return false
  if (request.batch_enabled) {
    return batchItemsForSource(request.batch_items ?? [], request.source_mode).some((item) => item.enabled !== false)
  }
  if (request.source_mode === 'url') return isHttpVideoUrl(request.source_url)
  return isSupportedVideoPath(request.video_path)
}

export function sourceRequirementMessage(request: GenerateRequest) {
  if (request.source_mode === 'document') return '当前发布版只支持本地视频和视频链接。请选择视频素材。'
  if (request.batch_enabled) return '请先添加至少一个批量素材后继续。'
  if (request.source_mode === 'url') return '请输入有效的视频链接，例如 https://...'
  return cleanPath(request.video_path) ? '请选择 MP4、MKV、MOV、WEBM 等视频文件。' : '请选择本地视频文件后继续。'
}
