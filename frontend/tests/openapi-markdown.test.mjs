import assert from 'node:assert/strict'
import test from 'node:test'

import { normalizeOpenApiMarkdown } from '../src/utils/openapi-markdown.js'

test('restores a heading and table flattened into one line', () => {
  const source = '用途：根据 SKU 查询。 ### 具体返回字段 | 返回字段 | 查出的内容 | | --- | --- | | `code` | 业务状态码 | | `data.items` | 数据列表 |'

  assert.equal(
    normalizeOpenApiMarkdown(source),
    [
      '用途：根据 SKU 查询。',
      '',
      '### 具体返回字段',
      '',
      '| 返回字段 | 查出的内容 |',
      '| --- | --- |',
      '| `code` | 业务状态码 |',
      '| `data.items` | 数据列表 |',
    ].join('\n'),
  )
})

test('keeps correctly formatted OpenAPI Markdown unchanged', () => {
  const source = '### 返回字段\n\n| 字段 | 说明 |\n| --- | --- |\n| `code` | 状态码 |'

  assert.equal(normalizeOpenApiMarkdown(source), source)
})

test('does not split ordinary inline pipe text', () => {
  const source = '值可以写成 `foo | bar`，也可以使用普通文本。'

  assert.equal(normalizeOpenApiMarkdown(source), source)
})
