import assert from 'node:assert/strict'
import test from 'node:test'

import {
  extractToolResultHtml,
  getToolResultHtml,
  getToolResultSeverity,
  getRunActivity,
  groupProcessBlocks,
  hasRunningProcessBlocks,
  mergeToolBlocks,
} from '../src/utils/agent-chat-blocks.js'

test('classifies explicit policy and user rejections as warnings', () => {
  for (const result of [
    'Error: PreToolUse:Bash hook error: [/usr/bin/python3 pre_tool_use.py]: [workspace_isolation] 拒绝:危险命令模式。所有路径与命令必须在工作区内',
    '[workspace_isolation] 拒绝：Read 路径越界:/etc/passwd',
    'Permission to use Bash has been denied.',
    "The user doesn't want to proceed with this tool use.",
    JSON.stringify({ error: '[workspace_isolation] 拒绝:平台托管文件禁止修改或覆盖' }),
  ]) assert.equal(getToolResultSeverity(result, true), 'warning', result)
})

test('keeps actual execution errors red, including hook failures and OS permissions', () => {
  for (const result of [
    'Exit code 1: command failed',
    'bash: command not found',
    'cat: /tmp/file: Permission denied',
    'Error: PreToolUse:Bash hook error: Traceback: SyntaxError',
    'Connection refused',
    'MCP tool timed out',
    JSON.stringify({ error: 'Invalid parameters' }),
    undefined,
  ]) assert.equal(getToolResultSeverity(result, true), 'error', result)
  assert.equal(getToolResultSeverity('[workspace_isolation] 拒绝:quoted log', false), '')
})

test('classifies stored tool results without changing the original error flag', () => {
  const [block] = mergeToolBlocks([
    { type: 'tool_use', name: 'Bash', tool_use_id: 'blocked-call' },
    { type: 'tool_result', tool_use_id: 'blocked-call', is_error: true, content: '[workspace_isolation] 拒绝:危险命令模式' },
  ])
  assert.equal(getToolResultSeverity(block.result, block.is_error), 'warning')
  assert.equal(block.is_error, true)
})

test('merges a non-adjacent tool result into its call', () => {
  const blocks = [
    {
      type: 'tool_use',
      name: 'Read',
      tool_use_id: 'call-1',
      input: { path: 'a.txt' },
      duration_ms: 1250,
    },
    { type: 'text', content: '处理中' },
    { type: 'tool_result', tool_use_id: 'call-1', content: 'done' },
  ]

  const merged = mergeToolBlocks(blocks)

  assert.equal(merged.length, 2)
  assert.equal(merged[0].name, 'Read')
  assert.equal(merged[0].result, 'done')
  assert.equal(merged[0].resultHtml, '')
  assert.equal(merged[0].duration_ms, 1250)
  assert.equal(merged[1].type, 'text')
  assert.equal(blocks[0].endTime, undefined)
})

test('matches out-of-order results by tool id', () => {
  const merged = mergeToolBlocks([
    { type: 'tool_use', name: 'First', tool_use_id: 'call-1' },
    { type: 'tool_use', name: 'Second', tool_use_id: 'call-2' },
    { type: 'tool_result', tool_use_id: 'call-1', content: 'first result' },
    { type: 'tool_result', tool_use_id: 'call-2', content: 'second result' },
  ])

  assert.deepEqual(merged.map(block => block.result), ['first result', 'second result'])
})

test('falls back to the latest unresolved call when ids are absent', () => {
  const merged = mergeToolBlocks([
    { type: 'tool_use', name: 'Bash' },
    { type: 'tool_result', content: 'ok' },
  ])

  assert.equal(merged.length, 1)
  assert.equal(merged[0].result, 'ok')
})

test('keeps a genuinely orphaned result visible', () => {
  const merged = mergeToolBlocks([
    { type: 'tool_result', tool_use_id: 'missing', content: 'orphan' },
  ])

  assert.equal(merged.length, 1)
  assert.equal(merged[0].type, 'tool_use')
  assert.equal(merged[0].result, 'orphan')
})

test('extracts raw s_html from a nested tool result', () => {
  const html = '  <div onclick="run()"><script>run()</script></div>  '
  const result = JSON.stringify({ code: 0, data: { output: { s_html: html } } })

  assert.equal(extractToolResultHtml(result), html)
})

test('restores the full persisted preview when diagnostic JSON has been truncated', () => {
  const html = '<section>' + '评分结果'.repeat(4000) + '</section>'
  const content = JSON.stringify({ data: { s_html: html } }).slice(0, 12000) + '\n[已截断]'
  assert.equal(extractToolResultHtml(content), '')
  for (const calls of [[], [{ type: 'tool_use', name: 'Score', tool_use_id: 'score' }]]) {
    const [block] = mergeToolBlocks([...calls, {
      type: 'tool_result', tool_use_id: 'score', content, resultHtml: html,
    }])
    assert.equal(block.result, content)
    assert.equal(getToolResultHtml(block), html)
    assert.equal(getToolResultHtml(mergeToolBlocks([block])[0]), html)
  }
})

test('extracts raw s_html from an object response', () => {
  const html = '<section>global function preview</section>'
  const response = { code: 0, data: { s_html: html } }

  assert.equal(extractToolResultHtml(response), html)
})

test('extracts raw html from a nested tool result', () => {
  const html = '<main><h1>HTML field</h1></main>'
  const result = JSON.stringify({ code: 0, data: { output: { html } } })

  assert.equal(extractToolResultHtml(result), html)
})

test('prefers s_html and skips empty HTML result fields', () => {
  const legacyHtml = '<section>legacy</section>'
  const standardHtml = '<section>standard</section>'

  assert.equal(
    extractToolResultHtml(JSON.stringify({ s_html: legacyHtml, html: standardHtml })),
    legacyHtml,
  )
  assert.equal(
    extractToolResultHtml(JSON.stringify({ s_html: '  ', html: standardHtml })),
    standardHtml,
  )
  assert.equal(
    extractToolResultHtml(JSON.stringify({ html: '', data: { html: standardHtml } })),
    standardHtml,
  )
})

test('caches extracted s_html on merged tool blocks', () => {
  const html = '<section>cached</section>'
  const [block] = mergeToolBlocks([
    { type: 'tool_use', name: 'Render', tool_use_id: 'call-html' },
    {
      type: 'tool_result',
      tool_use_id: 'call-html',
      content: JSON.stringify({ data: { s_html: html } }),
    },
  ])

  assert.equal(block.resultHtml, html)
})

test('extracts s_html from a nested JSON string', () => {
  const html = '<section>raw</section>'
  const result = JSON.stringify({ data: JSON.stringify({ s_html: html }) })

  assert.equal(extractToolResultHtml(result), html)
})

test('ignores tool results without valid HTML fields', () => {
  assert.equal(extractToolResultHtml('not json'), '')
  assert.equal(extractToolResultHtml(JSON.stringify({ data: { value: 1 } })), '')
  assert.equal(extractToolResultHtml(JSON.stringify({ s_html: null })), '')
  assert.equal(extractToolResultHtml(JSON.stringify({ html: { body: 'not raw HTML' } })), '')
})

test('handles unresolved tool calls before a result is available', () => {
  const block = { type: 'tool_use', name: 'Pending' }
  const cache = new WeakMap()

  assert.equal(getToolResultHtml(block, cache), '')
  assert.equal(getToolResultHtml(block, cache), '')
  assert.deepEqual(cache.get(block), { result: undefined, html: '' })
})

test('groups adjacent thinking and tool calls while preserving text order', () => {
  const intro = { type: 'text', content: '开始查询' }
  const thinking = { type: 'thinking', content: '分析参数' }
  const firstTool = { type: 'tool_use', name: 'Search' }
  const progress = { type: 'text', content: '数据已拿到' }
  const secondTool = { type: 'tool_use', name: 'Lookup' }

  const segments = groupProcessBlocks([
    intro,
    thinking,
    firstTool,
    progress,
    secondTool,
  ])

  assert.deepEqual(segments, [
    { type: 'block', key: 'block-0', block: intro },
    {
      type: 'process_group',
      key: 'process-1',
      blocks: [thinking, firstTool],
    },
    { type: 'block', key: 'block-3', block: progress },
    {
      type: 'process_group',
      key: 'process-4',
      blocks: [secondTool],
    },
  ])
})

test('returns no empty process groups for ordinary message blocks', () => {
  const textBlock = { type: 'text', content: '完成' }
  assert.deepEqual(groupProcessBlocks([textBlock]), [
    { type: 'block', key: 'block-0', block: textBlock },
  ])
})

test('groups consecutive calls across usage records and blank text without changing stored blocks', () => {
  const first = { type: 'tool_use', tool_use_id: 'one', name: 'Read' }
  const second = { type: 'tool_use', tool_use_id: 'two', name: 'Bash' }
  const answer = { type: 'text', content: '文件已核对。' }
  const blocks = [
    { type: 'text', content: '\n' }, first,
    { type: 'tool_result', tool_use_id: 'one', content: 'file contents' },
    { type: 'usage', usage: { input_tokens: 10 } },
    { type: 'text', content: ' \n\t' }, second,
    { type: 'tool_result', tool_use_id: 'two', content: 'verified' },
    { type: 'usage', usage: { output_tokens: 20 } }, answer,
  ]
  const before = structuredClone(blocks)
  const segments = groupProcessBlocks(mergeToolBlocks(blocks))
  assert.equal(segments.length, 2)
  assert.equal(segments[0].type, 'process_group')
  assert.equal(segments[0].key, 'process-1')
  assert.deepEqual(segments[0].blocks.map(block => [block.name, block.result]), [
    ['Read', 'file contents'], ['Bash', 'verified'],
  ])
  assert.equal(segments[1].block.content, answer.content)
  assert.deepEqual(blocks, before)
})

test('streaming empty text becoming real text splits groups without losing call identity', () => {
  const first = { type: 'tool_use', name: 'Read', result: 'ready' }
  const progress = { type: 'text', content: '' }
  const second = { type: 'tool_use', name: 'Bash' }
  const blocks = [first, progress, second]
  const initial = groupProcessBlocks(blocks)
  assert.equal(initial.length, 1)
  assert.equal(initial[0].key, 'process-0')
  progress.content = '继续检查文件'
  const updated = groupProcessBlocks(blocks)
  assert.equal(updated.length, 3)
  assert.equal(updated[0].key, initial[0].key)
  assert.equal(updated[1].block, progress)
  assert.equal(updated[2].blocks[0], second)
})

test('usage-only and blank-only messages produce no empty summaries', () => {
  assert.deepEqual(groupProcessBlocks([{ type: 'usage', usage: {} }, { type: 'text', content: '  ' }]), [])
})

test('tracks running state per process group instead of per streamed response', () => {
  assert.equal(hasRunningProcessBlocks([
    { type: 'thinking', content: 'done', endTime: 100 },
    { type: 'tool_use', name: 'First', endTime: 200 },
  ]), false)

  assert.equal(hasRunningProcessBlocks([
    { type: 'tool_use', name: 'CompletedWithResult', result: '' },
  ]), false)

  assert.equal(hasRunningProcessBlocks([
    { type: 'thinking', content: 'next step' },
  ]), true)

  assert.equal(hasRunningProcessBlocks([
    { type: 'tool_use', name: 'NextTool', input: { query: 'sku' } },
  ]), true)
})

test('describes the active process in the same chronological segment', () => {
  assert.deepEqual(getRunActivity([
    { type: 'thinking', content: '已完成', endTime: 10 },
    { type: 'tool_use', name: 'Read', input: { file_path: '/workspace/src/App.vue' } },
  ]), { title: '正在读取文件', detail: 'App.vue', paused: false })

  assert.deepEqual(getRunActivity([], 'waiting_permission'), {
    title: '等待你确认下一步操作', detail: '', paused: true,
  })
  assert.deepEqual(getRunActivity([{ type: 'text', content: '正在输出' }]), {
    title: '正在生成回复', detail: '', paused: false,
  })
  assert.deepEqual(getRunActivity([
    { type: 'tool_use', name: 'Bash', input: { description: 'Planning targeted tests and build' } },
  ]), { title: '正在执行命令', detail: 'Planning targeted tests and build', paused: false })
})

test('keeps the latest thinking text as the visible process summary', () => {
  assert.equal(getRunActivity([
    { type: 'thinking', content: '先核对接口返回，再决定修改位置', endTime: 10 },
  ]).title, '先核对接口返回，再决定修改位置')
})

test('shows received thinking content while it streams and keeps empty thinking honest', () => {
  const block = { type: 'thinking', content: '' }
  assert.deepEqual(getRunActivity([block]), { title: '思考中', detail: '', paused: false })
  block.content = '先核对接口返回'
  assert.equal(getRunActivity([block]).detail, '先核对接口返回')
  block.content += '\n再定位失败原因'
  assert.equal(getRunActivity([block]).detail, '先核对接口返回 再定位失败原因')
  block.content = '分析'.repeat(100)
  assert.equal(getRunActivity([block]).detail, `${block.content.slice(0, 120)}…`)
  assert.equal(getRunActivity([]).title, '正在等待模型响应')
})

test('describes commands, web requests, sub tasks and named business tools', () => {
  const cases = [
    ['Bash', { command: 'npm run build' }, '正在执行命令', 'npm run build'],
    ['WebSearch', { query: '物流时效' }, '正在搜索资料', '物流时效'],
    ['WebFetch', { url: 'https://example.com/docs' }, '正在读取网页', 'https://example.com/docs'],
    ['Task', { prompt: '核对接口参数' }, '正在执行子任务', '核对接口参数'],
    ['mcp__business__lookup_orders', {}, '正在调用工具', 'lookup_orders'],
    ['CustomTool', {}, '正在调用工具', 'CustomTool'],
    ['Read', { file_path: `/${'directory/'.repeat(20)}report.csv` }, '正在读取文件', 'report.csv'],
  ]
  for (const [name, input, title, detail] of cases) {
    assert.deepEqual(getRunActivity([{ type: 'tool_use', name, input }]), { title, detail, paused: false })
  }
})

test('retains completed tool context between calls and distinguishes failures', () => {
  const block = { type: 'tool_use', name: 'Read', input: { file_path: '/workspace/report.csv' }, result: 'data', endTime: 10 }
  assert.deepEqual(getRunActivity([block]), {
    title: '读取文件', detail: 'report.csv 已完成', paused: false,
  })
  block.is_error = true
  block.result = 'Connection refused'
  assert.equal(getRunActivity([block]).title, '工具执行异常')
  block.result = '[workspace_isolation] 拒绝:路径越界'
  assert.equal(getRunActivity([block]).title, '调用被拦截')
  assert.equal(getRunActivity([block, { type: 'thinking', content: '继续核对' }]).detail, '继续核对')
})

test('keeps completed business tool summaries concise', () => {
  assert.deepEqual(getRunActivity([{
    type: 'tool_use',
    name: 'mcp__business__invoke_service_api',
    result: 'ok',
    endTime: 10,
  }]), {
    title: '调用工具', detail: 'invoke_service_api 已完成', paused: false,
  })
})

test('parallel progress includes the latest action and keeps unresolved calls active', () => {
  const blocks = [
    { type: 'tool_use', name: 'Read', input: { path: '/workspace/report.csv' } },
    { type: 'tool_use', name: 'WebSearch', input: { query: '物流时效' } },
  ]
  assert.deepEqual(getRunActivity(blocks), {
    title: '正在并行处理 2 项任务', detail: '正在搜索资料 物流时效', paused: false,
  })
  blocks[1].result = '搜索完成'
  assert.deepEqual(getRunActivity(blocks), { title: '正在读取文件', detail: 'report.csv', paused: false })
  assert.deepEqual(getRunActivity(blocks, 'waiting_permission'), {
    title: '等待你确认下一步操作', detail: '', paused: true,
  })
})
