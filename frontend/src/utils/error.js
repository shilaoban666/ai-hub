import { ElMessage } from 'element-plus'

/**
 * 获取友好的错误提示信息
 * @param {Error} error - axios 错误对象
 * @param {string} fallback - 默认提示信息
 * @returns {string} 友好的错误提示
 */
export function getErrorMessage(error, fallback = '操作失败') {
  // 优先使用自定义的友好提示
  if (error.friendlyMessage) {
    return error.friendlyMessage
  }

  // 然后尝试从响应中获取错误信息（优先 message，兼容 detail）
  const msg = error.response?.data?.message || error.response?.data?.detail
  if (msg) {
    if (typeof msg === 'string') {
      return msg
    }
    if (Array.isArray(msg) && msg.length > 0) {
      return msg[0].msg || fallback
    }
  }

  // 最后使用默认提示
  return fallback
}

/**
 * 显示错误提示
 * @param {Error} error - axios 错误对象
 * @param {string} fallback - 默认提示信息
 */
export function showError(error, fallback = '操作失败') {
  const message = getErrorMessage(error, fallback)
  ElMessage.error(message)
}
