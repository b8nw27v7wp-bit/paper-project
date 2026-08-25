import { apiClient, rootClient } from './client'

export async function fetchRootHealth() {
  const { data } = await rootClient.get('/health')
  return data
}

export async function fetchHealth() {
  const { data } = await apiClient.get('/health')
  return data
}

export async function fetchV1Detailed() {
  const { data } = await apiClient.get('/health/detailed')
  return data
}
