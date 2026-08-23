import axios from 'axios'

const api = axios.create({ timeout: 15000 })

export async function createPlan(goal_id: number, preferences?: { hours_per_day: number }) {
  const { data } = await api.post('/api/v1/plans', { goal_id, preferences })
  return data
}

export function subscribePlanStream(trace_id: string, handlers: {
  onThought?: (d: any) => void
  onTool?: (d: any) => void
  onTask?: (d: any) => void
  onDone?: (d: any) => void
  onError?: (e: any) => void
}) {
  const es = new EventSource(`/api/v1/plans/stream?trace_id=${trace_id}`)
  es.addEventListener('thought', (e: MessageEvent) => {
    try { handlers.onThought?.(JSON.parse((e as any).data)) } catch {}
  })
  es.addEventListener('tool_call', (e: MessageEvent) => {
    try { handlers.onTool?.(JSON.parse((e as any).data)) } catch {}
  })
  es.addEventListener('task_created', (e: MessageEvent) => {
    try { handlers.onTask?.(JSON.parse((e as any).data)) } catch {}
  })
  es.addEventListener('done', (e: MessageEvent) => {
    try { handlers.onDone?.(JSON.parse((e as any).data)) } catch {}
    es.close()
  })
  es.onerror = (e) => {
    handlers.onError?.(e)
    es.close()
  }
  return es
}

export async function getPlanLogs(trace_id: string) {
  const { data } = await api.get(`/api/v1/plans/${trace_id}/logs`)
  return data
}
