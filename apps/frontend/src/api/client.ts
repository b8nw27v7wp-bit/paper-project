import axios from 'axios'

/**
 * 统一 API 客户端
 * - baseURL 指向 /api/v1（由 vite.config.ts proxy 转发至 http://localhost:8000）
 * - 前端所有业务 API 通过此 client 访问，保证联调一致
 */
export const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

// 根探针单独 client（/health 不在 /api/v1 下）
export const rootClient = axios.create({
  baseURL: '/',
  timeout: 8000,
  headers: { 'Content-Type': 'application/json' },
})

export default apiClient
