import api from './request'

export const knowledgeApi = {
  getAccess() {
    return api.get('/knowledge/access')
  },
  getDepartmentOptions() {
    return api.get('/knowledge/department-options', { timeout: 30000 })
  },
  getSettings() {
    return api.get('/knowledge/settings')
  },
  saveSettings(payload) {
    return api.put('/knowledge/settings', payload)
  },
  testSettings() {
    return api.post('/knowledge/settings/test', null, { timeout: 60000 })
  },
  getIndices() {
    return api.get('/knowledge/indices', { timeout: 30000 })
  },
  getCategories(parentId) {
    return api.get('/knowledge/categories', { params: parentId ? { parent_id: parentId } : {}, timeout: 30000 })
  },
  getDocuments(params) {
    return api.get('/knowledge/documents', { params, timeout: 30000 })
  },
  getUploads(params) {
    return api.get('/knowledge/uploads', { params })
  },
  upload(formData, onUploadProgress) {
    return api.post('/knowledge/uploads', formData, { timeout: 0, onUploadProgress })
  },
  deleteUpload(id) {
    return api.delete(`/knowledge/uploads/${id}`, { timeout: 60000 })
  },
  retrieve(payload) {
    return api.post('/knowledge/retrieve', payload, { timeout: 60000 })
  },
  getDingtalkStatus() {
    return api.get('/knowledge/dingtalk/status')
  },
  getDingtalkAuthorizeUrl(redirectUri) {
    return api.get('/knowledge/dingtalk/authorize-url', { params: { redirect_uri: redirectUri } })
  },
  bindDingtalk(payload) {
    return api.post('/knowledge/dingtalk/bind', payload, { timeout: 30000 })
  },
  unbindDingtalk() {
    return api.delete('/knowledge/dingtalk/binding')
  },
  getDingtalkWorkspaces() {
    return api.get('/knowledge/dingtalk/workspaces', { timeout: 30000 })
  },
  resolveDingtalkFolder(link) {
    return api.get('/knowledge/dingtalk/resolve-folder', { params: { link }, timeout: 30000 })
  },
  getRecentDingtalkFolders() {
    return api.get('/knowledge/dingtalk/recent-folders')
  },
  getDingtalkFolders(parentNodeId) {
    return api.get('/knowledge/dingtalk/folders', { params: { parent_node_id: parentNodeId }, timeout: 30000 })
  },
  getUsage(params) {
    return api.get('/dashboard/summary/knowledge-usage', { params })
  },
  getUsageCalls(params) {
    return api.get('/dashboard/summary/knowledge-usage/calls', { params })
  },
}

export function knowledgeErrorText(err, fallback = '操作失败，请重试') {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  return detail?.message || err?.friendlyMessage || fallback
}
