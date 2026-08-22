import axios from 'axios'

const api = axios.create({ timeout: 8000 })

export interface Task {
  id: number
  goal_id: number
  title: string
  planned_start: string
  planned_end: string
  priority: number
  status: string
  source_agent?: string
  citations?: any
  created_at: string
}

export async function listTasks(params: { goal_id?: number; status?: string; page?: number; size?: number } = {}) {
  const { data } = await api.get('/api/v1/tasks', { params })
  return data
}

export async function updateTask(id: number, payload: Partial<Task>) {
  const { data } = await api.put(`/api/v1/tasks/${id}`, payload)
  return data
}

export async function batchCreateTasks(tasks: Partial<Task>[]) {
  const { data } = await api.post('/api/v1/tasks/batch', { tasks })
  return data
}

export async function completeTask(id: number, payload: { actual_duration: number; completion_rate: number; delay_reason?: string }) {
  const { data } = await api.post(`/api/v1/tasks/${id}/complete`, payload)
  return data
}

export async function deleteTask(id: number) {
  const { data } = await api.delete(`/api/v1/tasks/${id}`)
  return data
}
