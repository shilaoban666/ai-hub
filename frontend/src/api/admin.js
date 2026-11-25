import { aihubRequest } from './request'

export const adminApi = {
  getManagementUsers(params) {
    return aihubRequest.get('/admin/user-management/', { params, timeout: 120000 })
  },
  getUsers(params) {
    return aihubRequest.get('/admin/user-management/', { params })
  },
  createUser(data) {
    return aihubRequest.post('/admin/user-management/', data)
  },
  updateUser(userId, data) {
    return aihubRequest.put(`/admin/user-management/${userId}`, data)
  },
}
