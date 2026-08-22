import axios from 'axios'

const api = axios.create({ timeout: 8000 })

export interface Goal {
  id: number
  user_id: number
  title: string
  description?: string
  deadline: string
  subject?: string
  status: string
  created_at: string
  tasks?: any[]
}

export interface GoalCreate {
  title: string
  description?: string
  deadline: string
  subject?: string
  status?: string
}

export async function listGoals(params: { status?: string; page?: number; size?: number } = {}) {
  const { data } = await api.get('/api/v1/goals', { params })
  return data
}

export async function createGoal(payload: GoalCreate) {
  const { data } = await api.post('/api/v1/goals', payload)
  return data
}

export async function getGoal(id: number) {
  const { data } = await api.get(`/api/v1/goals/${id}`)
  return data
}

export async function updateGoal(id: number, payload: Partial<GoalCreate>) {
  const { data } = await api.put(`/api/v1/goals/${id}`, payload)
  return data
}

export async function deleteGoal(id: number) {
  const { data } = await api.delete(`/api/v1/goals/${id}`)
  return data
}
