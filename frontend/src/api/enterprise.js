import request from './request'
import { config } from '@/config'

export const enterpriseApi = {
  getAgentSettings() { return request.get('/admin/agent-settings') },
  saveAgentSettings(data) { return request.put('/admin/agent-settings/draft', data) },
  publishAgentSettings(data) { return request.post('/admin/agent-settings/publish', data) },
  getAgentRuntimeSettings() { return request.get('/agent-settings/runtime') },
  getWorkbenchSettings() { return request.get('/admin/workbench-settings') },
  getWorkbenchSettingsHistory(params) { return request.get('/admin/workbench-settings/history', { params }) },
  saveWorkbenchSettings(data) { return request.put('/admin/workbench-settings/draft', data) },
  publishWorkbenchSettings(data) { return request.post('/admin/workbench-settings/publish', data) },
  bootstrap({ signal } = {}) {
    return request.post('/bootstrap', null, {
      timeout: Math.max(config.apiTimeout, 30000),
      signal,
    })
  },
  getCredits() {
    return request.get('/credits/me')
  },
  claimDailyCredits() {
    return request.post('/credits/me/daily-claim')
  },
  getGlobalSettings() {
    return request.get('/global-settings')
  },
  updateGlobalSettings(data) {
    return request.put('/admin/global-settings', data)
  },
  getGlobalRuntimeEnvironment() {
    return request.get('/admin/global-settings/runtime-environment')
  },
  updateGlobalRuntimeEnvironment(data) {
    return request.put('/admin/global-settings/runtime-environment', data)
  },
  getCreditLedger(params) {
    return request.get('/credits/me/ledger', { params })
  },
  rechargeUserCredits(userId, data) {
    return request.post(`/admin/users/${userId}/credits/adjust`, data)
  },
  getUserCreditBalance(userId) {
    return request.get(`/admin/users/${userId}/credits`)
  },
  getPlatformModels() {
    return request.get('/admin/platform-models')
  },
  createPlatformModel(data) {
    return request.post('/admin/platform-models', data)
  },
  updatePlatformModel(id, data) {
    return request.put(`/admin/platform-models/${id}`, data)
  },
  deletePlatformModel(id) {
    return request.delete(`/admin/platform-models/${id}`)
  },
}
