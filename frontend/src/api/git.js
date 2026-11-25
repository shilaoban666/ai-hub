import request from './request'

// Git 操作超时 60s（仓库文件多时网络请求耗时较长）
const GIT_TIMEOUT = 60000

export const gitApi = {
  importSkill(data) {
    return request.post('/git/skills/import', data, { timeout: GIT_TIMEOUT })
  },
  testConnection(data) {
    return request.post('/git/test-connection', data, { timeout: GIT_TIMEOUT })
  },
  bind(skillId, data) {
    return request.post(`/git/skills/${skillId}/bind`, data, { timeout: GIT_TIMEOUT })
  },
  unbind(skillId) {
    return request.post(`/git/skills/${skillId}/unbind`)
  },
  getSyncStatus(skillId) {
    return request.get(`/git/skills/${skillId}/sync-status`)
  },
  push(skillId, data) {
    return request.post(`/git/skills/${skillId}/push`, data, { timeout: GIT_TIMEOUT })
  },
  pull(skillId, data) {
    return request.post(`/git/skills/${skillId}/pull`, data, { timeout: GIT_TIMEOUT })
  },
  getDiff(skillId) {
    return request.get(`/git/skills/${skillId}/diff`, { timeout: GIT_TIMEOUT })
  }
}
