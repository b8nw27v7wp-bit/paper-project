import { apiClient } from './client'

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
  const { data } = await apiClient.get('/tasks', { params })
  return data
}

export async function updateTask(id: number, payload: Partial<Task>) {
  const { data } = await apiClient.put(`/tasks/${id}`, payload)
  return data
}

export async function batchCreateTasks(tasks: Partial<Task>[]) {
  const { data } = await apiClient.post('/tasks/batch', { tasks })
  return data
}

export async function completeTask(id: number, payload: { actual_duration: number; completion_rate: number; delay_reason?: string }) {
  const { data } = await apiClient.post(`/tasks/${id}/complete`, payload)
  return data
}

export async function deleteTask(id: number) {
  const { data } = await apiClient.delete(`/tasks/${id}`)
  return data
}
