const KEY_VALUE_PATTERNS = [
  /(["']?(?:api[_-]?key|authorization|token|secret)["']?\s*[:=]\s*["']?)([^"',\s}]{8,})(["']?)/gi,
  /(Bearer\s+)([A-Za-z0-9._~+/-]{8,}=*)/gi,
]

const TOKEN_PATTERNS = [
  /\b(sk-[A-Za-z0-9_-]{8,})\b/g,
  /\b(tp-[A-Za-z0-9_-]{8,})\b/g,
  /\b(xai-[A-Za-z0-9_-]{8,})\b/g,
  /\b(AIza[0-9A-Za-z_-]{12,})\b/g,
]

export function redactSensitiveText(value: unknown): string {
  let text = value instanceof Error ? value.message : String(value ?? '')

  for (const pattern of KEY_VALUE_PATTERNS) {
    text = text.replace(pattern, '$1[redacted]$3')
  }

  for (const pattern of TOKEN_PATTERNS) {
    text = text.replace(pattern, '[redacted]')
  }

  return text
}
