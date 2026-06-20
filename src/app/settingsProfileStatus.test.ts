import { describe, expect, it } from 'vitest'

import { buildSettingsProfileStatus } from './settingsProfileStatus'

describe('settingsProfileStatus', () => {
  it('shows a saved and tested API-key profile when the key is saved', () => {
    const status = buildSettingsProfileStatus({
      profile: { has_api_key: true, last_test_ok: true },
      profileSaved: true,
      auth: 'api_key',
      notSavedLabel: '未保存到我的模型',
    })

    expect(status.label).toBe('已保存 · 测试通过')
    expect(status.hasRequiredAuth).toBe(true)
    expect(status.savedTestOk).toBe(true)
  })

  it('shows saved but missing key for API-key profiles without a saved key', () => {
    const status = buildSettingsProfileStatus({
      profile: { has_api_key: false, last_test_ok: true },
      profileSaved: true,
      auth: 'api_key',
      notSavedLabel: '未保存到我的模型',
    })

    expect(status.label).toBe('已保存配置 · 未保存 Key')
    expect(status.hasRequiredAuth).toBe(false)
    expect(status.savedTestOk).toBe(false)
  })

  it('does not require a key for gcloud or no-auth profiles', () => {
    const gcloud = buildSettingsProfileStatus({
      profile: { has_api_key: false, last_test_ok: true },
      profileSaved: true,
      auth: 'gcloud',
      notSavedLabel: '未保存到我的模型',
    })
    const none = buildSettingsProfileStatus({
      profile: { has_api_key: false, last_test_ok: false },
      profileSaved: true,
      auth: 'none',
      notSavedLabel: '未保存到我的语音',
    })

    expect(gcloud.label).toBe('已保存 · 测试通过')
    expect(gcloud.savedTestOk).toBe(true)
    expect(none.label).toBe('已保存 · 未测试')
    expect(none.savedTestOk).toBe(false)
  })

  it('distinguishes dirty profiles from never-saved profiles', () => {
    const dirty = buildSettingsProfileStatus({
      profile: { has_api_key: true, last_test_ok: false },
      profileSaved: false,
      auth: 'api_key',
      notSavedLabel: '未保存到我的模型',
    })
    const neverSaved = buildSettingsProfileStatus({
      profile: undefined,
      profileSaved: false,
      auth: 'api_key',
      notSavedLabel: '未保存到我的语音',
    })

    expect(dirty.label).toBe('有未保存更改')
    expect(dirty.savedTestOk).toBe(false)
    expect(neverSaved.label).toBe('未保存到我的语音')
    expect(neverSaved.savedTestOk).toBe(false)
  })
})
