import request from './request'

export const modelsApi = {
  getList(params) {
    return request.get('/models', { params })
  },

  getDetail(id) {
    return request.get(`/models/${id}`)
  },

  create(data) {
    return request.post('/models', data)
  },

  update(id, data) {
    return request.put(`/models/${id}`, data)
  },

  delete(id) {
    return request.delete(`/models/${id}`)
  }
}
