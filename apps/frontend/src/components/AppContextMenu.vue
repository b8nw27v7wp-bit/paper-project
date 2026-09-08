<template>
  <n-dropdown :show="show" :x="x" :y="y" :options="options" placement="bottom-start" trigger="manual" @clickoutside="show = false" @select="onSelect" />
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NDropdown } from 'naive-ui'

const router = useRouter()
const route = useRoute()
const show = ref(false)
const x = ref(0)
const y = ref(0)

const options = computed(() => [
  { label: '刷新', key: 'reload' },
  { label: '复制链接', key: 'copy' },
  { label: '返回首页', key: 'home', disabled: route.path === '/' },
  { label: '打开命令面板 Ctrl+K', key: 'palette' },
  { label: '快捷键 ?', key: 'shortcuts' },
  { type: 'divider', key: 'd1' },
  { label: '在新窗口打开', key: 'external' },
])

function onContextMenu(e: MouseEvent): void {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  const main = document.getElementById('main-content')
  if (main && !main.contains(e.target as Node)) return
  e.preventDefault()
  x.value = e.clientX
  y.value = e.clientY
  show.value = true
}
onMounted(() => window.addEventListener('contextmenu', onContextMenu))
onBeforeUnmount(() => window.removeEventListener('contextmenu', onContextMenu))
function onSelect(key: string): void {
  show.value = false
  if (key === 'reload') window.location.reload()
  else if (key === 'copy') navigator.clipboard.writeText(window.location.href).catch(() => {})
  else if (key === 'home') void router.push('/')
  else if (key === 'palette') window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))
  else if (key === 'shortcuts') window.dispatchEvent(new KeyboardEvent('keydown', { key: '?' }))
  else if (key === 'external') window.open(window.location.href, '_blank')
}
</script>
