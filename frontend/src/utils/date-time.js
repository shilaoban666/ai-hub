export const BEIJING_TIME_ZONE = 'Asia/Shanghai'

const TIME_ZONE_SUFFIX = /(Z|[+-]\d{2}:?\d{2})$/i
const DATE_TIME_WITHOUT_ZONE = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/
const formatterCache = new Map()

const getFormatter = (locale, options) => {
  const formatterOptions = { ...options, timeZone: BEIJING_TIME_ZONE }
  const key = `${locale}:${JSON.stringify(formatterOptions)}`
  if (!formatterCache.has(key)) {
    formatterCache.set(key, new Intl.DateTimeFormat(locale, formatterOptions))
  }
  return formatterCache.get(key)
}

export const parseBackendDateTime = (value) => {
  if (value === null || value === undefined || value === '') return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : new Date(value.getTime())
  }

  let normalized = value
  if (typeof value === 'string') {
    normalized = value.trim()
    if (!normalized) return null
    if (DATE_TIME_WITHOUT_ZONE.test(normalized) && !TIME_ZONE_SUFFIX.test(normalized)) {
      normalized = `${normalized.replace(' ', 'T')}Z`
    }
  }

  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export const formatBeijingDateTime = (value, options = {}) => {
  const { fallback = '-', locale = 'zh-CN', ...overrides } = options
  const date = parseBackendDateTime(value)
  if (!date) return fallback

  return getFormatter(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
    ...overrides,
  }).format(date)
}

export const formatBeijingDate = (value, options = {}) => {
  const { fallback = '-', locale = 'zh-CN', ...overrides } = options
  const date = parseBackendDateTime(value)
  if (!date) return fallback

  return getFormatter(locale, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    ...overrides,
  }).format(date)
}

export const getBeijingDateTimeParts = (value) => {
  const date = parseBackendDateTime(value)
  if (!date) return null

  return Object.fromEntries(
    getFormatter('en-CA', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hourCycle: 'h23',
    }).formatToParts(date)
      .filter(part => part.type !== 'literal')
      .map(part => [part.type, part.value]),
  )
}

export const isPastDateTime = (value, now = Date.now()) => {
  const date = parseBackendDateTime(value)
  return date ? date.getTime() < Number(now) : false
}
