// composer 追问合并：running 态走 steer，idle 走新建；纯函数便于单测
// 不改 SSE/包络契约，包络解析仍走 api/plans 内 isApiEnvelope

export type ComposerAction = 'steer' | 'create' | 'noop'

export function resolveComposerAction(
  status: string,
  traceId: string | null | undefined,
  rawText: string,
): ComposerAction {
  const text = (rawText ?? '').trim()
  if (!text) return 'noop'
  if (status === 'running') {
    if (!traceId) return 'noop'
    return 'steer'
  }
  return 'create'
}

export function composerPlaceholder(status: string): string {
  if (status === 'running') return '输入追问，回车发送到当前运行'
  return '描述目标… @提及目标 /快捷命令，如：30天过六级，每天2小时'
}
