import axios from 'axios'
import { config } from '@/config'
import { canRecoverRequest, isServiceUnavailable } from '@/utils/service-recovery'
import { serviceRecoveryFor } from '@/utils/service-availability'

export async function getAccessTokenForRequest() {
  return localStorage.getItem('access_token')
}

let isRefreshing = false
let failedQueue = []

function requireLogin() {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

function unwrapResponse(body) {
  if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
    return body.data
  }
  return body
}

function normalizeError(error) {
  const body = error.response?.data
  if (body && typeof body === 'object' && 'message' in body) {
    body.detail = body.message
  }
  return error
}

function processQueue(error, token = null) {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })
  failedQueue = []
}

async function doRefreshToken() {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) {
    throw new Error('No refresh token')
  }

  const response = await axios.post('/api/auth/refresh', {
    refresh_token: refreshToken,
  })

  const data = unwrapResponse(response.data)
  const { access_token, refresh_token: new_refresh_token } = data
  localStorage.setItem('access_token', access_token)
  if (new_refresh_token) {
    localStorage.setItem('refresh_token', new_refresh_token)
  }
  return access_token
}

export async function refreshAccessToken() {
  if (isRefreshing) {
    return new Promise((resolve, reject) => {
      failedQueue.push({ resolve, reject })
    })
  }

  isRefreshing = true
  try {
    const accessToken = await doRefreshToken()
    processQueue(null, accessToken)
    return accessToken
  } catch (refreshError) {
    processQueue(refreshError, null)
    if (isServiceUnavailable(refreshError)) {
      refreshError.message = refreshError.friendlyMessage = '服务暂时不可用，请稍后重试'
      throw refreshError
    }
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    requireLogin()
    throw refreshError
  } finally {
    isRefreshing = false
  }
}

function createAxiosInstance(baseURL) {
  const recovery = serviceRecoveryFor(baseURL)
  const instance = axios.create({
    baseURL,
    timeout: config.apiTimeout,
  })

  instance.interceptors.request.use(
    async cfg => {
      const accessToken = await getAccessTokenForRequest()
      if (accessToken) {
        cfg.headers.Authorization = `Bearer ${accessToken}`
      }
      return cfg
    },
    error => Promise.reject(error)
  )

  instance.interceptors.response.use(
    response => {
      recovery.noteSuccess()
      return unwrapResponse(response.data)
    },
    async error => {
      normalizeError(error)
      const originalRequest = error.config

      if (isServiceUnavailable(error)) {
        const readOnly = ['get', 'head'].includes((originalRequest?.method || 'get').toLowerCase())
        const message = readOnly
          ? '服务暂时不可用，请稍后重试'
          : '服务暂时不可用；已提交的操作请恢复后核实结果，再决定是否重试'
        error.message = error.friendlyMessage = message
        if (error.response) error.response.data = { detail: message }
        if (canRecoverRequest(error)) {
          const authorization = originalRequest.headers?.Authorization || ''
          return recovery.recover(error, remaining => {
            const currentToken = localStorage.getItem('access_token')
            if (authorization !== (currentToken ? `Bearer ${currentToken}` : '')) {
              throw new axios.CanceledError('登录状态已变化，请重新加载页面')
            }
            return instance({
              ...originalRequest,
              _serviceRecoveryAttempt: true,
              timeout: Math.min(originalRequest.timeout || config.apiTimeout, remaining),
            })
          }, { signal: originalRequest.signal })
        }
        return Promise.reject(error)
      }

      if (originalRequest?.skipAuthRefresh) return Promise.reject(error)

      if (error.response?.status === 401 && !originalRequest._retry) {
        if (originalRequest.url?.includes('/auth/login') || originalRequest.url?.includes('/auth/refresh')) {
          return Promise.reject(error)
        }

        if (!originalRequest.headers?.Authorization) {
          return Promise.reject(error)
        }

        originalRequest._retry = true
        try {
          const accessToken = await refreshAccessToken()
          originalRequest.headers.Authorization = `Bearer ${accessToken}`
          return instance(originalRequest)
        } catch (refreshError) {
          return Promise.reject(refreshError)
        }
      }

      if (error.response?.status === 403) {
        error.friendlyMessage = '权限不足，请联系管理员开通相关权限'
      }

      console.error('API Error:', error)
      return Promise.reject(error)
    }
  )

  return instance
}

const aihubRequest = createAxiosInstance('/api')

export { aihubRequest }
export default aihubRequest
