<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between">
      <h2 class="text-lg font-semibold">目标管理 (F01) · 智能规划 (F02)</h2>
      <n-space>
        <n-select v-model:value="filterStatus" :options="statusOpts" style="width: 160px" placeholder="状态" clearable @update:value="load" />
        <n-button type="primary" @click="openCreate">新建目标</n-button>
      </n-space>
    </div>

    <n-card size="small">
      <n-data-table :columns="columns" :data="items" :pagination="false" :loading="loading" :row-key="(r:any)=>r.id" />
      <div class="flex justify-end mt-4">
        <n-pagination v-model:page="page" :page-size="size" :item-count="total" :page-sizes="[10,20,50]" show-size-picker @update:page="load" @update:page-size="onSize" />
      </div>
    </n-card>

    <n-modal v-model:show="showModal" preset="card" :title="editing ? '编辑目标' : '新建目标'" style="width: 640px">
      <GoalForm ref="formRef" :value="form" @update:value="form=$event" />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showModal=false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 智能规划 -->
    <n-modal v-model:show="showPlan" preset="card" title="智能规划 · SSE" style="width: 720px">
      <n-space vertical>
        <n-card size="small" v-if="planGoal">目标: {{ planGoal.title }} ({{ new Date(planGoal.deadline).toLocaleDateString() }})</n-card>
        <n-form label-placement="left" label-width="100" size="small">
          <n-form-item label="每日时长"><n-input-number v-model:value="planHours" :min="1" :max="8" /> 小时</n-form-item>
        </n-form>
        <n-button type="primary" :loading="planning" @click="doPlan" v-if="!traceId">开始生成</n-button>
        <PlanStream v-if="traceId" :trace-id="traceId" :mentor="mentorMsg" @done="onPlanDone" />
      </n-space>
      <template #footer>
        <n-space justify="end"><n-button @click="showPlan=false">关闭</n-button><n-button type="primary" @click="goCalendar" v-if="traceId">查看日历</n-button></n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NCard, NSpace, NButton, NSelect, NDataTable, NPagination, NModal, useMessage, NTag, NForm, NFormItem, NInputNumber } from 'naive-ui'
import GoalForm from '@/components/GoalForm.vue'
import PlanStream from '@/components/PlanStream.vue'
import { listGoals, createGoal, updateGoal, deleteGoal, getGoal } from '@/api/goals'
import { createPlan } from '@/api/plans'

const router = useRouter()
const message = useMessage()
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const filterStatus = ref<string | null>(null)
const statusOpts = [{ label: '进行中', value: 'active' }, { label: '已归档', value: 'archived' }]

const showModal = ref(false)
const editing = ref<any>(null)
const form = ref<any>({ title: '', description: '', deadline: null, subject: '', status: 'active' })
const formRef = ref<any>(null)
const saving = ref(false)

const showPlan = ref(false)
const planGoal = ref<any>(null)
const planHours = ref(4) // 默认4h更长排期，用户可调1-8
const traceId = ref<string|null>(null)
const mentorMsg = ref('')
const planning = ref(false)

const columns: any = [
  { title: 'ID', key: 'id', width: 60 },
  { title: '标题', key: 'title', ellipsis: { tooltip: true } },
  { title: '科目', key: 'subject', width: 80 },
  { title: '截止', key: 'deadline', width: 150, render: (r:any)=> new Date(r.deadline).toLocaleDateString() },
  { title: '状态', key: 'status', width: 80, render: (r:any)=> h(NTag, { type: r.status==='active'?'success':'warning', size:'small' }, { default: ()=> r.status }) },
  { title: '操作', key: 'actions', width: 360, render: (r:any)=> h(NSpace, {}, { default: ()=> [
    h(NButton, { size:'small', type:'primary', onClick: ()=>openPlan(r) }, { default: ()=> '智能规划' }),
    h(NButton, { size:'small', onClick: ()=>viewTasks(r) }, { default: ()=> '任务' }),
    h(NButton, { size:'small', onClick: ()=>openEdit(r) }, { default: ()=> '编辑' }),
    h(NButton, { size:'small', type:'error', onClick: ()=>remove(r) }, { default: ()=> '删除' }),
  ]}) },
]

function openPlan(row:any){ planGoal.value=row; planHours.value=4; traceId.value=null; mentorMsg.value=''; showPlan.value=true }
async function doPlan(){
  if(!planGoal.value) return
  planning.value=true
  try {
    const res = await createPlan(planGoal.value.id, { hours_per_day: planHours.value })
    traceId.value = res.data.trace_id
    mentorMsg.value = res.data.mentor_msg
    message.success(`已生成 ${res.data.tasks.length} 任务`)
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
  finally { planning.value=false }
}
function onPlanDone(){ load() }
function goCalendar(){ showPlan.value=false; router.push(`/calendar?goal_id=${planGoal.value.id}`) }

async function load() {
  loading.value = true
  try {
    const res = await listGoals({ status: filterStatus.value || undefined, page: page.value, size: size.value })
    items.value = res.data.items
    total.value = res.data.total
  } catch (e:any) { message.error(e?.response?.data?.msg || e.message) }
  finally { loading.value = false }
}
function onSize(v:number){ size.value=v; page.value=1; load() }

function openCreate(){
  editing.value=null
  form.value={ title:'', description:'', deadline: Date.now()+2*86400000, subject:'', status:'active' }
  showModal.value=true
}
async function openEdit(row:any){
  try {
    const res = await getGoal(row.id)
    const g = res.data
    editing.value=g
    form.value={ title:g.title, description:g.description, deadline: new Date(g.deadline).getTime(), subject:g.subject, status:g.status }
    showModal.value=true
  } catch(e:any){ message.error(e?.response?.data?.msg || e.message) }
}
async function toggleArchived(row:any){
  try {
    await updateGoal(row.id, { status: row.status==='active' ? 'archived' : 'active' })
    message.success('已更新')
    load()
  } catch(e:any){ message.error(e?.response?.data?.msg || e.message) }
}
async function remove(row:any){
  if(!confirm(`删除目标 ${row.title} ? 关联任务将级联删除`)) return
  try { await deleteGoal(row.id); message.success('已删除'); load() } catch(e:any){ message.error(e?.response?.data?.msg || e.message) }
}
function viewTasks(row:any){
  router.push(`/calendar?goal_id=${row.id}`)
}
async function save(){
  try { await formRef.value?.validate() } catch { return }
  saving.value=true
  try {
    const payload:any = { ...form.value }
    // deadline: number -> ISO
    if (typeof payload.deadline === 'number') payload.deadline = new Date(payload.deadline).toISOString()
    if (editing.value) {
      await updateGoal(editing.value.id, payload)
      message.success('已更新')
    } else {
      await createGoal(payload)
      message.success('已创建')
    }
    showModal.value=false
    load()
  } catch(e:any){ message.error(e?.response?.data?.msg || e?.response?.data?.data?.errors?.[0]?.msg || e.message) }
  finally { saving.value=false }
}

onMounted(load)
</script>
