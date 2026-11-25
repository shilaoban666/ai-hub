import { defineStore } from 'pinia'
import {
  aihubRequest,
  refreshAccessToken as refreshAccessTokenRequest,
} from '@/api/request'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: localStorage.getItem('access_token'),
    refreshToken: localStorage.getItem('refresh_token'),
    user: null,
    isAuthenticated: !!localStorage.getItem('access_token'),
    _fetchingUser: false,
  }),

  actions: {
    async login(username, password) {
      const data = await aihubRequest.post(
        '/auth/login',
        { username, password },
        { skipAuthRefresh: true },
      )
      this.setTokens(data.access_token, data.refresh_token)
      if (data.user) {
        this.user = data.user
      } else {
        await this.fetchUserInfo()
      }
      return this.user
    },

    async refreshAccessToken() {
      if (!this.refreshToken) {
        throw new Error('No refresh token available')
      }
      const accessToken = await refreshAccessTokenRequest()
      this.accessToken = accessToken
      this.refreshToken = localStorage.getItem('refresh_token') || this.refreshToken
      this.isAuthenticated = true
      return accessToken
    },

    async fetchUserInfo() {
      if (this._fetchingUser) return this.user
      if (this.user) return this.user
      this._fetchingUser = true
      try {
        const response = await aihubRequest.get('/auth/me')
        this.user = response
        return this.user
      } catch (error) {
        console.error('获取用户信息失败:', error)
        if (error?.response?.status === 401) {
          this.clearAuth()
        }
        throw error
      } finally {
        this._fetchingUser = false
      }
    },

    async logout() {
      try {
        await aihubRequest.post('/auth/logout', null, { skipAuthRefresh: true })
      } catch {
        // Ignore logout request errors and clear local session.
      } finally {
        this.clearAuth()
        window.location.assign('/login')
      }
    },

    setTokens(accessToken, refreshToken) {
      this.accessToken = accessToken
      this.refreshToken = refreshToken
      this.isAuthenticated = true
      localStorage.setItem('access_token', accessToken)
      localStorage.setItem('refresh_token', refreshToken)
    },

    clearAuth() {
      this.accessToken = null
      this.refreshToken = null
      this.user = null
      this.isAuthenticated = false
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    },

    hasPermission(permission) {
      if (!this.user) return false
      if (this.user.is_superuser) return true
      const perms = this.user.permissions || []
      return perms.some(p => p === '*' || p === permission)
    },

    hasRole(role) {
      if (!this.user) return false
      if (this.user.is_superuser) return true
      return (this.user.roles || []).includes(role)
    },
  },
})
