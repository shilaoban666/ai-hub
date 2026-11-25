import api from './request'

export const dashboardApi = {
  recoverCreditRun(scope, runId, options = {}) {
    const query = options.forceRelease ? '?force_release=true' : options.forceSettle ? '?force_settle=true' : ''
    return api.post(`/dashboard/${scope}/credit-usage/runs/${encodeURIComponent(runId)}/recover${query}`)
  },
  settleAllCreditRuns(scope, params = {}) {
    return api.post(`/dashboard/${scope}/credit-usage/runs/settle-all`, null, { params, timeout: 0 })
  },
  getPersonalCreditUsage(section = '', params = {}) {
    return api.get(`/dashboard/personal/credit-usage${section ? `/${section}` : ''}`, { params })
  },
  getSummaryCreditUsage(section = '', params = {}) {
    return api.get(`/dashboard/summary/credit-usage${section ? `/${section}` : ''}`, { params })
  },
  getPersonalTokenUsage(params = {}) {
    return api.get('/dashboard/personal/token-usage', { params })
  },

  getSummaryTokenUsage(params = {}) {
    return api.get('/dashboard/summary/token-usage', { params })
  },

  getSummaryTokenUsageUserDetail(userId, params = {}) {
    return api.get(`/dashboard/summary/token-usage/users/${userId}`, { params })
  }
}
