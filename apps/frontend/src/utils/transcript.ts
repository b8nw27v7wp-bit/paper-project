// 转录纯函数（Wave-2 P0-1/P0-2）：reviewer 判定 + done 标签优先级，便于单测
// 渲染仍走 TranscriptView.vue 分支，此处仅收敛“先判 cancelled 再判 approved”语义

export interface DoneLabelInput {
  cancelled?: boolean
  approved?: boolean
}

// done 行优先级：cancelled > approved===false > 完成（与 workbench done.cancelled 衔接）
export function formatDoneLabel(item: DoneLabelInput): '已取消' | '已拒绝' | '完成' {
  if (item.cancelled) return '已取消'
  if (item.approved === false) return '已拒绝'
  return '完成'
}

export function isReviewerKind(kind: string): boolean {
  return kind === 'reviewer'
}

// reviewer 复核评分高亮（AgentWorkbenchView displayTranscript 复用，不改 kind）
export function highlightReviewScore(raw: string): string {
  return (raw ?? '').replace(/(复核评分\s*\d+)/, '**$1**')
}

// issues 归一化：非数组（string/对象/缺失）一律回 []，避免 string 被 v-for 逐字渲染
export function normIssues(v: unknown): string[] {
  return Array.isArray(v) ? (v as string[]) : []
}
