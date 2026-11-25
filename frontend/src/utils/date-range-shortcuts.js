import { getBeijingDateTimeParts } from './date-time.js'

const ROLLING_RANGES = [
  { text: '近3天', days: 3 },
  { text: '近7天', days: 7 },
  { text: '近30天', days: 30 },
  { text: '近90天', days: 90 },
  { text: '近180天', days: 180 },
  { text: '近1年', days: 365 },
]
const DAYS_PER_WEEK = 7

export function createDateRangeShortcuts(now = () => new Date()) {
  const range = (offset) => {
    const { year, month, day } = getBeijingDateTimeParts(now())
    // Date pickers read local calendar fields; retain Beijing's date in any browser time zone.
    const end = new Date(Number(year), Number(month) - 1, Number(day))
    const start = new Date(end)
    start.setDate(end.getDate() - offset(end))
    return [start, end]
  }

  return [
    ...ROLLING_RANGES.map(({ text, days }) => ({
      text,
      value: () => range(() => days - 1),
    })),
    { text: '本周', value: () => range(end => (end.getDay() + DAYS_PER_WEEK - 1) % DAYS_PER_WEEK) },
    { text: '本月', value: () => range(end => end.getDate() - 1) },
  ]
}
