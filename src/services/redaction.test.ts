import { describe, expect, it } from 'vitest'
import { redactSensitiveText } from './redaction'

describe('redactSensitiveText', () => {
  it('redacts common provider token prefixes', () => {
    const skToken = `sk-${'abc1234567890'}`
    const tpToken = `tp-${'token-plan-secret-123456'}`
    const text = `failed with ${skToken} and ${tpToken}`

    expect(redactSensitiveText(text)).not.toContain(skToken)
    expect(redactSensitiveText(text)).not.toContain(tpToken)
  })

  it('redacts bearer and api_key values in structured errors', () => {
    const bearerToken = `xai-${'super-secret-token-123'}`
    const apiKey = `AI${'zaVerySecretValue12345'}`
    const text = `Authorization: Bearer ${bearerToken}, "api_key": "${apiKey}"`

    const redacted = redactSensitiveText(text)

    expect(redacted).toContain('Bearer [redacted]')
    expect(redacted).toContain('"api_key": "[redacted]"')
  })
})
