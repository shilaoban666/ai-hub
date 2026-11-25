import assert from 'node:assert/strict'
import test from 'node:test'
import { bootstrapFailure } from '../src/utils/bootstrap-error.js'

test('timeouts and connection failures have actionable messages without a settings link', () => {
  for (const code of ['ECONNABORTED', 'ETIMEDOUT']) {
    const failure = bootstrapFailure({ code, message: 'timeout exceeded' })
    assert.match(failure.message, /初始化超时/)
    assert.equal(failure.settings, null)
  }
  assert.match(bootstrapFailure({ code: 'ERR_NETWORK' }).message, /检查网络和本地服务/)
})

test('configuration errors retain the correct administration link', () => {
  const failure = bootstrapFailure({ response: { data: {
    detail: { message: '未发布', data: { code: 'ASSISTANT_SETTINGS_NOT_PUBLISHED' } },
  } } })
  assert.equal(failure.message, '管理员尚未发布全局智能体设置')
  assert.equal(failure.settings.path, '/admin/assistant-settings')
  const model = bootstrapFailure({ response: { data: {
    message: '默认平台模型不可用', data: { code: 'DEFAULT_MODEL_UNAVAILABLE' },
  } } })
  assert.equal(model.message, '默认平台模型不可用')
  assert.equal(model.settings.path, '/admin/workbench-settings')
})

test('server and client failures preserve their reason instead of falling back to generic retry', () => {
  for (const error of [
    { response: { data: { detail: '默认平台模型不存在' } } },
    { response: { data: { detail: { message: '工作区准备失败' } } } },
    { friendlyMessage: '权限不足，请联系管理员' },
    new Error('默认助手配置无效'),
  ]) {
    assert.notEqual(bootstrapFailure(error).message, '工作台初始化失败，请稍后重试。')
    assert.equal(bootstrapFailure(error).settings, null)
  }
  assert.equal(bootstrapFailure({}).message, '工作台初始化失败，请稍后重试。')
})
