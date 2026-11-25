import request from './request'
import { config } from '@/config'

export const skillsApi = {
  getMetadataOptions() {
    return request.get('/skills/metadata-options')
  },

  getList(params) {
    return request.get('/skills', { params })
  },

  getDetail(id) {
    return request.get(`/skills/${id}`)
  },

  create(data) {
    return request.post('/skills', data)
  },

  update(id, data) {
    return request.put(`/skills/${id}`, data)
  },

  delete(id) {
    return request.delete(`/skills/${id}`)
  },

  getCollaborators(id) {
    return request.get(`/skills/${id}/collaborators`)
  },

  addCollaborator(id, data) {
    return request.post(`/skills/${id}/collaborators`, data)
  },

  removeCollaborator(id, userId) {
    return request.delete(`/skills/${id}/collaborators/${userId}`)
  },

  import(file) {
    const formData = new FormData()
    formData.append('file', file)
    // 导入需要等待文件上传、解压和保存，使用独立于普通 API 的超时时间。
    return request.post('/skills/import', formData, { timeout: config.skillImportTimeout })
  },

  importInto(id, file) {
    const formData = new FormData()
    formData.append('file', file)
    return request.post(`/skills/${id}/import`, formData, {
      timeout: config.skillImportTimeout
    })
  },

  export(id) {
    return request.get(`/skills/${id}/export`, { responseType: 'blob' })
  },

  // 发布技能
  release(id, data) {
    return request.post(`/skills/${id}/release`, data)
  },

  // 获取发布历史
  getReleases(id) {
    return request.get(`/skills/${id}/releases`)
  },

  restoreRelease(id, releaseId) {
    return request.post(`/skills/${id}/releases/${releaseId}/restore`)
  },

  // 上传封面
  uploadCover(id, file) {
    const formData = new FormData()
    formData.append('file', file)
    return request.post(`/skills/${id}/cover`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
  },

  // 删除封面
  deleteCover(id) {
    return request.delete(`/skills/${id}/cover`)
  },

  // 切换公开/私有可见性
  toggleVisibility(id) {
    return request.put(`/skills/${id}/visibility`)
  }
}

// 公开技能 API（无需认证）
export const publicSkillsApi = {
  getMetadataOptions() {
    return request.get('/public/skills/metadata-options')
  },

  getList(params) {
    return request.get('/public/skills', { params })
  },

  getDetail(id) {
    return request.get(`/public/skills/${id}`)
  },

  getReleases(id) {
    return request.get(`/public/skills/${id}/releases`)
  }
}
