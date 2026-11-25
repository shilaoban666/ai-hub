import request from './request'

export const promptTemplatesApi = {
  getList(params) {
    return request.get('/prompt-templates', { params })
  },

  // 系统、公开和自己的模板，供需要跨工作区复用的场景使用
  getUsable(params) {
    return request.get('/prompt-templates/usable', { params })
  },

  getDetail(id) {
    return request.get(`/prompt-templates/${id}`)
  },

  create(data) {
    return request.post('/prompt-templates', data)
  },

  update(id, data) {
    return request.put(`/prompt-templates/${id}`, data)
  },

  delete(id) {
    return request.delete(`/prompt-templates/${id}`)
  },

  toggleVisibility(id) {
    return request.put(`/prompt-templates/${id}/visibility`)
  }
}

export const publicPromptTemplatesApi = {
  getList(params) {
    return request.get('/public/prompt-templates', { params })
  },

  getDetail(id) {
    return request.get(`/public/prompt-templates/${id}`)
  }
}
