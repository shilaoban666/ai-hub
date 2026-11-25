import request from './request'

export const mcpsApi = {
  getList(params) {
    return request.get('/mcps', { params })
  },

  getDetail(id) {
    return request.get(`/mcps/${id}`)
  },

  create(data) {
    return request.post('/mcps', data)
  },

  update(id, data) {
    return request.put(`/mcps/${id}`, data)
  },

  delete(id) {
    return request.delete(`/mcps/${id}`)
  },

  uploadCover(id, file) {
    const formData = new FormData()
    formData.append('file', file)
    return request.post(`/mcps/${id}/cover`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  },

  deleteCover(id) {
    return request.delete(`/mcps/${id}/cover`)
  },

  toggleVisibility(id) {
    return request.put(`/mcps/${id}/visibility`)
  }
}

export const publicMcpsApi = {
  getList(params) {
    return request.get('/public/mcps', { params })
  },

  getDetail(id) {
    return request.get(`/public/mcps/${id}`)
  }
}
