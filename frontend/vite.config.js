import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync } from 'node:fs'
import { parseEnv } from 'node:util'
import { resolve } from 'path'

const rootDir = resolve(import.meta.dirname, '..')

export default defineConfig(() => {
  const env = parseEnv(readFileSync(resolve(rootDir, '.env'), 'utf8'))
  const clientDefines = Object.fromEntries(
    Object.entries(env)
      .filter(([key]) => key.startsWith('VITE_'))
      .map(([key, value]) => [`import.meta.env.${key}`, JSON.stringify(value)])
  )
  const backendTarget = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

  return {
    define: {
      ...clientDefines,
    },
    envDir: false,
    envPrefix: [],
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(import.meta.dirname, 'src'),
      },
    },
    optimizeDeps: {
      include: ['jszip'],
    },
    server: {
      host: '0.0.0.0',
      port: Number(env.VITE_FRONTEND_PORT) || 15173,
      allowedHosts: true,
      cors: true,
      proxy: {
        '/api': {
          target: backendTarget,
          changeOrigin: true,
        },
        '/aihub/api': {
          target: backendTarget,
          changeOrigin: true,
          rewrite: path => path.replace(/^\/aihub/, ''),
        },
        '/releases': {
          target: backendTarget,
          changeOrigin: true,
        },
        '/uploads': {
          target: backendTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      chunkSizeWarningLimit: Infinity,
      rolldownOptions: {
        onLog(level, log, defaultHandler) {
          if (log.code === 'INVALID_ANNOTATION') return
          defaultHandler(level, log)
        },
      },
    },
  }
})
