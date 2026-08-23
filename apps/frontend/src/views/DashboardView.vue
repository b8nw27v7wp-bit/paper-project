<template>
  <div class="space-y-4">
    <h2 class="text-lg font-semibold">可视化大屏 (P3)</h2>
    <n-space>
      <n-select v-model:value="range" :options="[{label:'7天',value:'7d'},{label:'30天',value:'30d'}]" style="width:120px" @update:value="load" />
      <n-button @click="load">刷新</n-button>
      <n-button @click="runExp('A')">实验A 多Agent</n-button>
      <n-button @click="runExp('B')">实验B 有记忆</n-button>
    </n-space>
    <n-grid :cols="3" :x-gap="12">
      <n-gi><n-card size="small" title="完成率"><div class="text-2xl font-bold text-green-600">{{ (overview.completion_rate*100).toFixed(1) }}%</div></n-card></n-gi>
      <n-gi><n-card size="small" title="拖延率"><div class="text-2xl font-bold text-red-600">{{ (overview.delay_rate*100).toFixed(1) }}%</div></n-card></n-gi>
      <n-gi><n-card size="small" title="平均负荷"><div class="text-2xl font-bold">{{ overview.avg_load }} h/天</div></n-card></n-gi>
    </n-grid>
    <n-card size="small" title="趋势">
      <v-chart :option="trendOpt" style="height:300px" autoresize />
    </n-card>
    <n-card size="small" title="实验结果">
      <n-code :code="JSON.stringify(exp, null, 2)" language="json" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { NCard, NSpace, NButton, NSelect, NGrid, NGi, NCode, useMessage } from 'naive-ui'
import VChart from 'vue-echarts'
import axios from 'axios'

const range = ref('7d')
const overview = ref({ completion_rate:0, delay_rate:0, avg_load:0 })
const trendData = ref({ dates:[], rates:[], loads:[] })
const exp = ref({})
const message = useMessage()

const trendOpt = computed(()=>({
  tooltip:{trigger:'axis'},
  legend:{data:['完成率','负荷']},
  xAxis:{type:'category', data: trendData.value.dates},
  yAxis:[{type:'value', max:1},{type:'value'}],
  series:[
    {name:'完成率', type:'line', data: trendData.value.rates, smooth:true},
    {name:'负荷', type:'bar', yAxisIndex:1, data: trendData.value.loads}
  ]
}))

async function load(){
  try {
    const r = await axios.get(`/api/v1/stats/overview?range=${range.value}`)
    overview.value = r.data.data
    const t = await axios.get(`/api/v1/stats/trend?range=${range.value === '7d' ? '7d' : '30d'}`)
    trendData.value = t.data.data
  } catch(e:any){ message.error(e?.response?.data?.msg||e.message) }
}
async function runExp(type:string){
  const r = await axios.post(`/api/v1/stats/experiment?type=${type}`)
  exp.value = r.data.data
  message.success(`实验${type}完成`)
}
onMounted(load)
</script>
