import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyAgentRunTerminalEvent,
  getAgentRunFailurePresentation,
  getAgentRunErrorDetails,
  getAgentRunStatusMeta,
} from '../src/utils/agent-run-state.js'

test('maps active run phases to user-facing states', () => {
  assert.equal(getAgentRunStatusMeta('connecting').label, '提交中')
  assert.equal(getAgentRunStatusMeta('queued').label, '排队中')
  assert.equal(getAgentRunStatusMeta('running').label, '执行中')
  assert.equal(getAgentRunStatusMeta('waiting_permission').label, '等待确认')
  assert.equal(getAgentRunStatusMeta('stopping').label, '正在停止')
})

test('normalizes failed and cancelled terminal events without conflating them', () => {
  const failed = { phase: 'running', failed: false, cancelled: false }
  assert.equal(applyAgentRunTerminalEvent(failed, {
    type: 'error', content: 'provider failed', error_code: 'provider_error',
  }), true)
  assert.equal(failed.phase, 'failed')
  assert.equal(failed.failed, true)
  assert.equal(failed.cancelled, false)
  assert.equal(failed.error, 'provider failed')
  assert.equal(failed.errorCode, 'provider_error')
  assert.equal(failed.terminalEventReceived, true)

  const cancelled = { phase: 'stopping', failed: false, cancelled: false, error: 'old' }
  assert.equal(applyAgentRunTerminalEvent(cancelled, {
    type: 'cancelled', content: 'cancelled', error_code: 'cancelled',
  }), true)
  assert.equal(cancelled.phase, 'cancelled')
  assert.equal(cancelled.failed, false)
  assert.equal(cancelled.cancelled, true)
  assert.equal(cancelled.error, '')
  assert.equal(cancelled.terminalEventReceived, true)
})

test('does not display terminal or unknown phases as active', () => {
  assert.equal(getAgentRunStatusMeta('succeeded'), null)
  assert.equal(getAgentRunStatusMeta('failed'), null)
  assert.equal(getAgentRunStatusMeta('idle'), null)
})

test('presents model balance failures as one actionable business message', () => {
  assert.deepEqual(
    getAgentRunFailurePresentation(
      '模型服务余额不足，请联系管理员充值或切换其他模型后重试。',
      'model_balance_insufficient',
    ),
    {
      title: '模型服务余额不足',
      message: '请联系管理员充值，或切换其他模型后重试。',
      retryLabel: '余额恢复后重试',
    },
  )
})

test('distinguishes execution timeout, model timeout, connection failure and invalid models', () => {
  assert.equal(getAgentRunFailurePresentation('', 'runtime_timeout').title, '本次执行超时')
  assert.equal(getAgentRunFailurePresentation('', 'model_request_timeout').title, '模型请求超时')
  assert.equal(getAgentRunFailurePresentation('', 'model_connection_failed').title, '模型服务连接中断')
  assert.equal(getAgentRunFailurePresentation('', 'model_not_supported').title, '当前模型不可用')
})

test('keeps the upstream diagnostic and source when friendly copy is displayed', () => {
  const state = { phase: 'running' }
  applyAgentRunTerminalEvent(state, {
    type: 'error', content: '模型服务繁忙', error_code: 'model_rate_limited',
    metadata: { error_origin: 'upstream', error_detail: 'API Error: 429 rate_limit_error; request_id=req-42' },
  })
  assert.deepEqual(state.errorDetails, {
    source: '模型上游', code: 'model_rate_limited', detail: 'API Error: 429 rate_limit_error; request_id=req-42',
  })
  assert.equal(getAgentRunErrorDetails('raw legacy error').source, '来源未确认')
})
