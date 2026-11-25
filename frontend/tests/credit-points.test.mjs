import assert from 'node:assert/strict'
import test from 'node:test'

import { formatCreditPoints } from '../src/utils/credit-points.js'

test('formats credit values with exactly two decimal places', () => {
  assert.equal(formatCreditPoints(2), '2.00')
  assert.equal(formatCreditPoints('1.236'), '1.24')
  assert.equal(formatCreditPoints(1234.5), '1,234.50')
})

test('uses a fallback for missing credit values', () => {
  assert.equal(formatCreditPoints(null), '--')
  assert.equal(formatCreditPoints(undefined), '--')
  assert.equal(formatCreditPoints(''), '--')
  assert.equal(formatCreditPoints('not-a-number'), '--')
})
