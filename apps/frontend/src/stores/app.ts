import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const health = ref<any>(null)
  const setHealth = (v: any) => (health.value = v)
  return { health, setHealth }
})
