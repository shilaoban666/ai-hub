// Only transport failures are retried. Backend business 503s have an explicit
// marker: the gateway uses the same JSON envelope, so its shape is insufficient.
export function isServiceUnavailable(error) {
  if (error?.code === 'ERR_CANCELED') return false
  const status = error?.response?.status
  if (status === 503 && error?.response?.headers?.['x-aihub-error'] === 'business') return false
  return [502, 503, 504].includes(status) || (!error?.response && error?.code === 'ERR_NETWORK')
}

export function canRecoverRequest(error) {
  const cfg = error?.config
  return cfg && !cfg.skipServiceRecovery && !cfg._serviceRecoveryAttempt
    && ['get', 'head'].includes((cfg.method || 'get').toLowerCase())
    && isServiceUnavailable(error)
}

export function createServiceRecovery({
  onChange = () => {}, maxWait = 120000, now = Date.now,
  setTimer = setTimeout, clearTimer = clearTimeout,
} = {}) {
  let active = 0
  let unavailable = false
  const wakeups = new Set()
  const notify = () => onChange({ active, unavailable })

  function wait(ms, signal) {
    return new Promise((resolve, reject) => {
      let timer
      const finish = (error) => {
        clearTimer(timer)
        wakeups.delete(wake)
        signal?.removeEventListener('abort', abort)
        if (error) reject(error)
        else resolve()
      }
      const wake = () => finish()
      const abort = () => finish(Object.assign(new Error('请求已取消'), { code: 'ERR_CANCELED' }))
      if (signal?.aborted) { abort(); return }
      wakeups.add(wake)
      signal?.addEventListener('abort', abort, { once: true })
      timer = setTimer(wake, ms)
    })
  }

  return {
    retryNow() { [...wakeups].forEach(wake => wake()) },
    noteSuccess() {
      if (!active && unavailable) { unavailable = false; notify() }
    },
    async recover(initialError, retry, { signal } = {}) {
      active += 1
      notify()
      const started = now()
      let lastError = initialError
      let attempt = 0
      try {
        while (now() - started < maxWait) {
          await wait(Math.min(1000 * 2 ** Math.min(attempt++, 4), 15000, maxWait - (now() - started)), signal)
          if (now() - started >= maxWait) break
          try {
            const result = await retry(maxWait - (now() - started))
            unavailable = false
            return result
          } catch (error) {
            if (['ECONNABORTED', 'ETIMEDOUT'].includes(error?.code) && now() - started >= maxWait) break
            if (!isServiceUnavailable(error)) throw error
            lastError = error
          }
        }
        unavailable = true
        throw lastError
      } finally {
        active -= 1
        notify()
      }
    },
  }
}
