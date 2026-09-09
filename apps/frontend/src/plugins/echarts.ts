// ECharts 按需注册（vue-echarts v6 + echarts v5 必须显式 use，否则挂载即抛
// "Renderer 'undefined' is not imported"，并会阻断同 flush 的转录渲染）。
// 覆盖全站用到的图与组件：GraphCanvas(graph)/Dashboard(line/bar/scatter)/Experiments(line/bar)/KnowledgeGraph(graph)/LargeScreen(line/bar/heatmap)。
import {
  BarChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
} from 'echarts/charts'
import {
  CalendarComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

use([
  CanvasRenderer,
  BarChart,
  GraphChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  CalendarComponent,
  DatasetComponent,
  GridComponent,
  LegendComponent,
  TitleComponent,
  ToolboxComponent,
  TooltipComponent,
  VisualMapComponent,
])
