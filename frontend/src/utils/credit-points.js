export const DEFAULT_CREDIT_DISPLAY_NAME = '积分'

export const creditDisplayName = value => (
  typeof value === 'string' && value.trim() ? value.trim() : DEFAULT_CREDIT_DISPLAY_NAME
)

export const formatCreditPoints = (value, fallback = '--') => {
  if (value === null || value === undefined || value === '') return fallback
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return numeric.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}
