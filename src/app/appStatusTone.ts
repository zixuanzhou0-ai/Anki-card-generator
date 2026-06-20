export type AppStatusTone = 'active' | 'warn' | 'ok' | 'idle'

const WARN_STATUS_PATTERN = /失败|缺少|不能|请先|不存在|错误|没有/
const OK_STATUS_PATTERN = /完成|通过|成功|可用|已打开|已切换|已套用|已保留/

export function buildAppStatusTone({
  appBusy,
  hasWorkerProgress,
  status,
}: {
  appBusy: boolean
  hasWorkerProgress: boolean
  status: string
}): AppStatusTone {
  if (appBusy || hasWorkerProgress) return 'active'
  if (WARN_STATUS_PATTERN.test(status)) return 'warn'
  if (OK_STATUS_PATTERN.test(status)) return 'ok'
  return 'idle'
}
