import request from './request'

export function uploadImage(file, purpose) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/upload/image', formData, {
    params: purpose ? { purpose } : undefined,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
