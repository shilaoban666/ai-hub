import api from './request'

export const feedbackApi = {
  save: (messageId, body) => api.put(`/feedback/messages/${messageId}`, body),
  remove: messageId => api.delete(`/feedback/messages/${messageId}`),
  list: params => api.get('/feedback', { params }),
  listMine: params => api.get('/feedback/mine', { params }),
  detail: (id, params = {}) => api.get(`/feedback/${id}`, { params }),
  mineDetail: (id, params = {}) => api.get(`/feedback/mine/${id}`, { params }),
  assign: (id, body) => api.patch(`/feedback/${id}/processing`, { ...body, action: 'assignment' }),
  process: (id, body) => api.patch(`/feedback/${id}/processing`, body),
}
