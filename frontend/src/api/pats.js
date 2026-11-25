import { iamRequest as authRequest } from './request'

export const patsApi = {
  create(name) {
    return authRequest.post('/pats/', { name })
  },

  getList(params) {
    return authRequest.get('/pats/list/', { params })
  },

  revoke(id) {
    return authRequest.delete(`/pats/${id}/`)
  }
}
