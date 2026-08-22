<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold">任务日历 / 甘特 (F03)</h2>
      <n-space>
        <n-select v-model:value="goalId" :options="goalOpts" placeholder="按目标筛选" clearable style="width:200px" @update:value="load" />
        <n-select v-model:value="statusFilter" :options="statusOpts" placeholder="状态" clearable style="width:140px" @update:value="load" />
        <n-button @click="load">刷新</n-button>
        <n-button type="primary" @click="showBatch=true">批量建任务(演示)</n-button>
      </n-space>
    </div>

    <n-card size="small">
      <FullCalendar :options="calOpts" ref="calRef" />
    </n-card>

    <n-card size="small" title="列表视图">
      <n-data-table :columns="cols" :data="tasks" :pagination="false" size="small" :row-key="(r:any)=>r.id" />
    </n-card>

    <TaskDrawer v-model="showDrawer" :task="current" @refresh="load" @delete="onDelete" />

    <n-modal v-model:show="showBatch" preset="card" title="批量创建任务 (POST /tasks/batch)" style="width:640px">
      <n-form :model="batch" label-placement="left" label-width="90">
        <n-form-item label="目标ID"><n-input-number v-model:value="batch.goal_id" class="w-full" /></n-form-item>
        <n-form-item label="标题前缀"><n-input v-model:value="batch.prefix" placeholder="如: 背单词" /></n-form-item>
        <n-form-item label="天数"><n-input-number v-model:value="batch.days" :min="1" :max="14" class="w-full" /></n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end"><n-button @click="showBatch=false">取消</n-button><n-button type="primary" :loading="batching" @click="doBatch">生成</n-button></n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h } from 'vue'
import { useRoute } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NDataTable, NModal, NForm, NFormItem, NInput, NInputNumber, NTag, useMessage } from 'naive-ui'
import FullCalendar from '@fullcalendar/vue3'
import dayGridPlugin from '@fullcalendar/daygrid'
import timeGridPlugin from '@fullcalendar/timegrid'
import interactionPlugin from '@fullcalendar/interaction'
import { listTasks, updateTask, batchCreateTasks, deleteTask } from '@/api/tasks'
import { listGoals } from '@/api/goals'
import TaskDrawer from '@/components/TaskDrawer.vue'

const route = useRoute()
const message = useMessage()
const goalId = ref<number | null>(Number(route.query.goal_id) || null)
const statusFilter = ref<string | null>(null)
const goalOpts = ref<any[]>([])
const statusOpts = [{ label:'todo', value:'todo' },{ label:'doing', value:'doing' },{ label:'done', value:'done' },{ label:'delayed', value:'delayed' }]
const tasks = ref<any[]>([])
const showDrawer = ref(false)
const current = ref<any>(null)
const calRef = ref<any>(null)
const showBatch = ref(false)
const batch = ref({ goal_id: 1, prefix: '学习任务', days: 3 })
const batching = ref(false)

const events = computed(()=> tasks.value.map(t=>({
  id: String(t.id),
  title: t.title,
  start: t.planned_start,
  end: t.planned_end,
  backgroundColor: t.status==='done' ? '#10b981' : t.status==='doing' ? '#f59e0b' : t.status==='delayed' ? '#ef4444' : '#3b82f6',
  borderColor: 'transparent',
})))

const calOpts = computed(()=>({
  plugins: [dayGridPlugin, timeGridPlugin, interactionPlugin],
  initialView: 'timeGridWeek',
  headerToolbar: { left: 'prev,next today', center: 'title', right: 'dayGridMonth,timeGridWeek,timeGridDay' },
  editable: true,
  selectable: true,
  locale: 'zh-cn',
  events: events.value,
  eventClick: (info:any)=>{ const id = Number(info.event.id); current.value = tasks.value.find(t=>String(t.id)===String(id)); showDrawer.value=true },
  eventDrop: async (info:any)=>{ const id=Number(info.event.id); try{ await updateTask(id, { planned_start: info.event.start.toISOString(), planned_end: info.event.end?.toISOString() }); message.success('已更新时间'); load() } catch(e:any){ message.error(e?.response?.data?.msg||e.message); info.revert() } },
  eventResize: async (info:any)=>{ const id=Number(info.event.id); try{ await updateTask(id, { planned_start: info.event.start.toISOString(), planned_end: info.event.end?.toISOString() }); message.success('已调整时长'); load() } catch(e:any){ message.error(e?.response?.data?.msg||e.message); info.revert() } },
}))

const cols:any = [
  { title:'ID', key:'id', width:60 },
  { title:'标题', key:'title' },
  { title:'开始', key:'planned_start', width:170, render:(r:any)=> new Date(r.planned_start).toLocaleString() },
  { title:'结束', key:'planned_end', width:170, render:(r:any)=> new Date(r.planned_end).toLocaleString() },
  { title:'优先级', key:'priority', width:80 },
  { title:'状态', key:'status', width:90, render:(r:any)=> h(NTag, { type: r.status==='done'?'success': r.status==='delayed'?'error': 'info', size:'small' }, { default: ()=> r.status }) },
  { title:'操作', key:'actions', width:160, render:(r:any)=> h(NSpace, {}, { default: ()=> [
    h(NButton, { size:'small', onClick: ()=>{ current.value=r; showDrawer.value=true } }, { default: ()=> '打卡' }),
    h(NButton, { size:'small', type:'error', onClick: ()=>onDelete(r.id) }, { default: ()=> '删除' }),
  ]}) },
]

async function load(){
  try {
    const res = await listTasks({ goal_id: goalId.value || undefined, status: statusFilter.value || undefined, page:1, size:100 })
    tasks.value = res.data.items
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
}
async function loadGoals(){
  try { const res = await listGoals({ page:1, size:100 }); goalOpts.value = res.data.items.map((g:any)=>({ label:`#${g.id} ${g.title}`, value:g.id })); if(!batch.value.goal_id && res.data.items[0]) batch.value.goal_id=res.data.items[0].id } catch {}
}
async function doBatch(){
  batching.value=true
  try {
    const base = new Date(); base.setHours(9,0,0,0)
    const tasksPayload = Array.from({ length: batch.value.days }, (_,i)=>{
      const s = new Date(base); s.setDate(base.getDate()+i)
      const e = new Date(s); e.setHours(s.getHours()+1)
      return { goal_id: batch.value.goal_id, title: `${batch.value.prefix} ${i+1}`, planned_start: s.toISOString(), planned_end: e.toISOString(), priority: 3 }
    })
    await batchCreateTasks(tasksPayload)
    message.success(`已批量创建 ${tasksPayload.length} 条`)
    showBatch.value=false
    load()
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
  finally { batching.value=false }
}
async function onDelete(id:number){
  if(!confirm('删除任务?')) return
  try { await deleteTask(id); message.success('已删除'); load() } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
}
onMounted(()=>{ loadGoals(); load() })
</script>
