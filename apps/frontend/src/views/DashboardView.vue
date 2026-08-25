<template>
  <div class="space-y-8">
    <div class="flex items-end justify-between">
      <div>
        <h2 class="text-[24px] font-semibold tracking-[-0.02em] text-ink">大屏</h2>
        <p class="mt-1 text-[13px] text-muted">P3 评估 · 完成率/拖延/负荷 · 浅色极简</p>
      </div>
      <n-space>
        <n-select v-model:value="range" :options="[{label:'7天',value:'7d'},{label:'30天',value:'30d'}]" style="width:120px" @update:value="load" />
        <n-button strong secondary @click="load">刷新</n-button>
        <n-button @click="runExp('A')">实验A</n-button>
        <n-button @click="runExp('B')">实验B</n-button>
      </n-space>
    </div>
    <n-grid :cols="3" :x-gap="16">
      <n-gi><n-card class="apple-card"><div class="text-[11px] tracking-widest text-muted">完成率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.completion_rate*100).toFixed(1) }}%</div></n-card></n-gi>
      <n-gi><n-card class="apple-card"><div class="text-[11px] tracking-widest text-muted">拖延率</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ (overview.delay_rate*100).toFixed(1) }}%</div></n-card></n-gi>
      <n-gi><n-card class="apple-card"><div class="text-[11px] tracking-widest text-muted">平均负荷</div><div class="mt-2 text-[28px] font-semibold tracking-[-0.03em] text-ink">{{ overview.avg_load }}<span class="text-[14px] font-normal text-muted"> h/天</span></div></n-card></n-gi>
    </n-grid>
    <n-card class="apple-card">
      <template #header><span class="text-[13px] font-semibold text-ink">趋势</span></template>
      <v-chart :option="trendOpt" style="height:300px" autoresize />
    </n-card>
    <n-card class="apple-card">
      <template #header><span class="text-[13px] font-semibold text-ink">实验</span></template>
      <n-code :code="JSON.stringify(exp, null, 2)" language="json" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NSelect, NGrid, NGi, NCode, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import { fetchStatsOverview, fetchStatsTrend, runStatsExperiment } from '@/api/stats'

const range = ref('7d')
const overview = ref({ completion_rate:0, delay_rate:0, avg_load:0 })
const trendData = ref<{dates:any[]; rates:any[]; loads:any[]}>({ dates:[], rates:[], loads:[] })
const exp = ref({})
const message = useMessage()

const trendOpt = computed(()=>({
  tooltip:{trigger:'axis'},
  legend:{data:['完成率','负荷']},
  xAxis:{type:'category', data: (trendData.value.dates as any)},
  yAxis:[{type:'value', max:1},{type:'value'}],
  series:[
    {name:'完成率', type:'line', data: (trendData.value.rates as any), smooth:true},
    {name:'负荷', type:'bar', yAxisIndex:1, data: (trendData.value.loads as any)}
  ]
}))

async function load(){
  try {
    const r = await fetchStatsOverview(range.value)
    overview.value = r.data
    const t = await fetchStatsTrend(range.value === '7d' ? '7d' : '30d')
    trendData.value = t.data
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
}
async function runExp(type:'A'|'B'){
  try {
    const r = await runStatsExperiment(type)
    exp.value = r.data
    message.success(`实验${type}完成`)
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
}
onMounted(load)
</script>
