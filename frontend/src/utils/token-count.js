const TOKEN_UNITS = [
  { threshold: 1e9, suffix: 'B' },
  { threshold: 1e6, suffix: 'M' },
  { threshold: 1e3, suffix: 'K' },
]
const PRECISION = 2

export function formatTokenCount(value) {
  if (value == null || String(value).trim() === '' || !Number.isFinite(Number(value))) return '无'
  const count = Number(value)
  let unitIndex = TOKEN_UNITS.findIndex(item => Math.abs(count) >= item.threshold)
  if (unitIndex === -1) return count.toLocaleString('en-US', { maximumFractionDigits: 0 })
  // Promote after rounding, so a boundary value never displays as 1,000K/M.
  if (unitIndex > 0 && Math.abs(Number((count / TOKEN_UNITS[unitIndex].threshold).toFixed(PRECISION))) >= 1000) unitIndex -= 1
  const unit = TOKEN_UNITS[unitIndex]
  return `${Number((count / unit.threshold).toFixed(PRECISION)).toLocaleString('en-US', { maximumFractionDigits: PRECISION })}${unit.suffix}`
}
