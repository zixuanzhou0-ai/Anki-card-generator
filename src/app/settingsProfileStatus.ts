import type { SavedApiProfile, SavedProfileAuth, SavedTtsProfile } from '../domain/types'

type SettingsProfile = Pick<SavedApiProfile | SavedTtsProfile, 'has_api_key' | 'last_test_ok'>

export type SettingsProfileStatus = {
  label: string
  hasRequiredAuth: boolean
  savedTestOk: boolean
}

export function buildSettingsProfileStatus({
  profile,
  profileSaved,
  auth,
  notSavedLabel,
}: {
  profile?: SettingsProfile
  profileSaved: boolean
  auth: SavedProfileAuth
  notSavedLabel: string
}): SettingsProfileStatus {
  const hasRequiredAuth = Boolean(profile?.has_api_key) || auth !== 'api_key'
  const savedTestOk = profileSaved && Boolean(profile?.last_test_ok) && hasRequiredAuth
  const label = profileSaved
    ? hasRequiredAuth
      ? `已保存 · ${profile?.last_test_ok ? '测试通过' : '未测试'}`
      : '已保存配置 · 未保存 Key'
    : profile
      ? '有未保存更改'
      : notSavedLabel

  return {
    label,
    hasRequiredAuth,
    savedTestOk,
  }
}
