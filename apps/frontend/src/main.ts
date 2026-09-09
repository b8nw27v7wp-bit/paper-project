import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { TopNavPlugin } from './plugins/topnav'
import './plugins/echarts'
import './style.css'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(TopNavPlugin)
app.mount('#app')
