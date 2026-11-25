import test from 'node:test'
import assert from 'node:assert/strict'

import {
  formatBeijingDate,
  formatBeijingDateTime,
  getBeijingDateTimeParts,
  isPastDateTime,
  parseBackendDateTime,
} from '../src/utils/date-time.js'

test('parses timezone-less backend timestamps as UTC', () => {
  assert.equal(
    parseBackendDateTime('2026-07-28 01:02:03').toISOString(),
    '2026-07-28T01:02:03.000Z',
  )
})

test('formats timestamps in Beijing time regardless of their source offset', () => {
  const options = { locale: 'zh-CN', second: undefined }
  assert.equal(formatBeijingDateTime('2026-07-28T01:02:03Z', options), '2026/07/28 09:02')
  assert.equal(formatBeijingDateTime('2026-07-28T09:02:03+08:00', options), '2026/07/28 09:02')
  assert.equal(formatBeijingDateTime('2026-07-28 01:02:03', options), '2026/07/28 09:02')
  assert.equal(formatBeijingDate('2026-07-27T16:30:00Z'), '2026/07/28')
})

test('provides Beijing calendar parts for chart labels', () => {
  assert.deepEqual(getBeijingDateTimeParts('2026-12-31T16:05:06Z'), {
    month: '01',
    day: '01',
    year: '2027',
    hour: '00',
    minute: '05',
    second: '06',
  })
})

test('compares expiry timestamps by their absolute instant', () => {
  assert.equal(isPastDateTime('2026-07-28T09:00:00+08:00', Date.parse('2026-07-28T01:00:01Z')), true)
  assert.equal(isPastDateTime('invalid', Date.now()), false)
})
