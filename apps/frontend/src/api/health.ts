import axios from 'axios'

const api = axios.create({
  timeout: 8000,
  headers: { 'Content-Type': 'application/json' },
})

export async function fetchRootHealth() {
  const { data } = await api.get('/health')
  return data
}

export async function fetchHealth() {
  const { data } = await api.get('/api/v1/health')
  return data
}

export async function fetchV1Detailed() {
  const { data } = await api.get('/api/v1/health/detailed')
  return data
}
