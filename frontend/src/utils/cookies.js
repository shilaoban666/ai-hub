/**
 * 清除所有 cookie（保留 CSRF token）
 */
export function clearAllCookies() {
  const cookies = document.cookie.split(';')
  // 保留 Django CSRF token
  const preservedCookies = ['csrftoken']

  for (let i = 0; i < cookies.length; i++) {
    const cookie = cookies[i]
    const eqPos = cookie.indexOf('=')
    const name = eqPos > -1 ? cookie.substr(0, eqPos).trim() : cookie.trim()

    // 跳过需要保留的 cookie
    if (preservedCookies.includes(name)) {
      continue
    }

    // 删除 cookie (设置过期时间为过去)
    document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`

    // 尝试删除带域名的 cookie
    const domain = window.location.hostname
    document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=${domain}`

    // 尝试删除父域名的 cookie
    const domainParts = domain.split('.')
    if (domainParts.length > 2) {
      const parentDomain = domainParts.slice(-2).join('.')
      document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.${parentDomain}`
    }
  }
}

/**
 * 获取指定名称的 cookie
 */
export function getCookie(name) {
  const value = `; ${document.cookie}`
  const parts = value.split(`; ${name}=`)
  if (parts.length === 2) {
    return parts.pop().split(';').shift()
  }
  return null
}

/**
 * 设置 cookie
 */
export function setCookie(name, value, days = 7) {
  const expires = new Date()
  expires.setTime(expires.getTime() + days * 24 * 60 * 60 * 1000)
  document.cookie = `${name}=${value};expires=${expires.toUTCString()};path=/`
}

/**
 * 删除指定名称的 cookie
 */
export function deleteCookie(name) {
  document.cookie = `${name}=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/`
}
