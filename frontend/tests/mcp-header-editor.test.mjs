import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/views/admin/components/McpHeaderEditor.vue', import.meta.url),
  'utf8',
)
const assetCenterSource = readFileSync(
  new URL('../src/views/admin/AssetCenter.vue', import.meta.url),
  'utf8',
)

test('request header values use a wrapping multiline editor', () => {
  assert.match(source, /type="textarea"/)
  assert.match(source, /:autosize="\{ minRows: 1, maxRows: 5 \}"/)
  assert.match(source, /resize="vertical"/)
  assert.doesNotMatch(source, /max-height:/)
  assert.match(source, /@keydown\.enter\.prevent/)
  assert.doesNotMatch(source, /type="password"/)
})

test('saved header values remain visible without reveal controls', () => {
  assert.doesNotMatch(source, /header-value-input--masked/)
  assert.doesNotMatch(source, /显示请求头值|隐藏请求头值/)
  assert.doesNotMatch(source, /-webkit-text-security/)
})

test('adding an Authorization header pre-fills the Bearer scheme', () => {
  assert.match(source, /name\.toLowerCase\(\) === 'authorization' \? 'Bearer ' : ''/)
})

test('saved request headers are write-only and blank edits preserve their values', () => {
  assert.match(assetCenterSource, /value: ''/)
  assert.match(assetCenterSource, /configured: item\.configured !== false/)
  assert.match(assetCenterSource, /entries\.push\(\[name, null\]\)/)
  assert.match(assetCenterSource, /entries\.push\(\[name, row\.value\]\)/)
})

test('connector authentication can reuse the current login without persisting its token', () => {
  assert.match(assetCenterSource, /value: 'current_user'/)
  assert.match(assetCenterSource, /工作台在线对话使用登录用户的 Bearer Token，不保存 Token/)
  assert.match(assetCenterSource, /后台渠道没有浏览器登录态/)
  assert.match(assetCenterSource, /headerDialog\.authMode/)
  assert.match(assetCenterSource, /row\.name\.trim\(\)\.toLowerCase\(\) !== 'authorization'/)
  assert.match(source, /allowAuthorization/)
})

test('connector authentication dialog has a compact structured empty state', () => {
  assert.match(assetCenterSource, /class="mcp-auth-dialog"/)
  assert.match(assetCenterSource, /class="auth-mode-summary"/)
  assert.match(source, /v-if="!rows\.length" class="header-empty"/)
  assert.match(source, />添加请求头<\/el-button>/)
  assert.doesNotMatch(source, /circle aria-label="添加请求头"/)
})
