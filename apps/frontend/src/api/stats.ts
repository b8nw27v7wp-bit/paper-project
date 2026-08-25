import { apiClient } from './client'

export async function fetchStatsOverview(range: string = '7d') {
  const { data } = await apiClient.get('/stats/overview', { params: { range } })
  return data
}

export async function fetchStatsTrend(range: string = '7d') {
  const { data } = await apiClient.get('/stats/trend', { params: { range } })
  return data
}

export async function runStatsExperiment(type: 'A' | 'B' = 'A') {
  const { data } = await apiClient.post('/stats/experiment', null, { params: { type } })
  return data
}
