<template>
  <div role="listbox" aria-label="快捷菜单" class="py-1">
    <button
      v-for="item in items"
      :key="item.key"
      role="option"
      :aria-label="item.label"
      class="w-full text-left px-2.5 py-1.5 rounded-[8px] hover:bg-[var(--c-surface)] transition-colors flex items-center justify-between gap-2"
      @mousedown.prevent="emit('select', item.key)"
    >
      <span class="text-[12px] font-medium text-ink truncate">{{ item.label }}</span>
      <span v-if="item.desc" class="text-[11px] text-muted truncate shrink-0">{{ item.desc }}</span>
    </button>
    <div v-if="!items.length" class="px-2.5 py-2 text-[12px] text-muted">无可用项</div>
  </div>
</template>

<script setup lang="ts">
export interface ComposerMenuItem {
  key: string
  label: string
  desc?: string
}

defineProps<{
  items: ComposerMenuItem[]
}>()

const emit = defineEmits<{
  (e: 'select', key: string): void
}>()
</script>
