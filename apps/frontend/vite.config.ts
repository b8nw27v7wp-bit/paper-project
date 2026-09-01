import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    // 已校验：/api/* 代理至后端的 FastAPI (8000)，SSE 需 ws:true + keep-alive
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Connection', 'keep-alive');
          });
        },
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    cssCodeSplit: true,
    minify: 'esbuild',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('naive-ui')) return 'vendor-naive'
            if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
            if (id.includes('@fullcalendar')) return 'vendor-calendar'
            if (id.includes('vue-router') || id.includes('pinia') || id.includes('vue/')) return 'vendor-vue'
            if (id.includes('axios')) return 'vendor-axios'
            if (id.includes('date-fns') || id.includes('dayjs')) return 'vendor-date'
            return 'vendor-misc'
          }
        },
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
      },
    },
  },
  optimizeDeps: {
    include: ['vue', 'vue-router', 'pinia', 'naive-ui', 'axios', 'echarts', 'vue-echarts', '@fullcalendar/vue3'],
  },
})
