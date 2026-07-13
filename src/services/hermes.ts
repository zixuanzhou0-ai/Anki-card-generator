import { invoke } from '@tauri-apps/api/core'

import type { HermesProxyStatus } from '../domain/types'
import { HERMES_GROK_BASE_URL, HERMES_GROK_MODEL } from '../domain/options'
import { isTauriRuntime } from './runtime'

function browserUnavailableStatus(): HermesProxyStatus {
  return {
    state: 'error',
    message: '浏览器预览模式不能管理 Hermes 本机代理，请运行桌面端。',
    base_url: HERMES_GROK_BASE_URL,
    model: HERMES_GROK_MODEL,
    managed: false,
    authenticated: false,
  }
}

export async function checkHermesProxy(): Promise<HermesProxyStatus> {
  if (!isTauriRuntime()) return browserUnavailableStatus()
  return invoke<HermesProxyStatus>('check_hermes_proxy')
}

export async function startHermesProxy(): Promise<HermesProxyStatus> {
  if (!isTauriRuntime()) return browserUnavailableStatus()
  return invoke<HermesProxyStatus>('start_hermes_proxy')
}

export async function stopOwnedHermesProxy(): Promise<HermesProxyStatus> {
  if (!isTauriRuntime()) return browserUnavailableStatus()
  return invoke<HermesProxyStatus>('stop_owned_hermes_proxy')
}