import assert from 'node:assert/strict'
import test from 'node:test'
import { readAgentStream } from '../src/utils/agent-stream.js'

const response = chunks => new Response(new ReadableStream({
  start(controller) {
    const bytes = new TextEncoder().encode(chunks)
    // Split inside UTF-8 characters and SSE delimiters.
    for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7))
    controller.close()
  },
}))

test('reconnect replays only unacknowledged text and preserves UTF-8', async () => {
  const state = {}
  const events = []
  const first = 'id: 1\ndata: {"type":"text","content":"刷新前"}\n\n'
  const next = 'id: 2\ndata: {"type":"text","content":"刷新后"}\n\n'
  await readAgentStream(response(first + next.slice(0, -1)), state, event => events.push(event))
  assert.equal(state.lastEventId, 1)
  await readAgentStream(response(first + next + 'id: 3\ndata: {"type":"stream_end"}\n\n'), state, event => events.push(event))
  assert.equal(events.filter(event => event.type === 'text').map(event => event.content).join(''), '刷新前刷新后')
  assert.equal(state.lastEventId, 3)
  assert.equal(state.streamEnded, true)
})

test('does not acknowledge a frame when handling fails', async () => {
  const state = { lastEventId: 4 }
  await assert.rejects(readAgentStream(response('id: 5\ndata: {"type":"text","content":"hi"}\n\n'), state, () => {
    throw new Error('render failed')
  }), /render failed/)
  assert.equal(state.lastEventId, 4)
})

test('Redis batches append after a snapshot and reconnect does not duplicate a batch', async () => {
  const state = {}
  let text = ''
  const handle = event => {
    if (event.type === 'snapshot_reset') text = ''
    if (event.type === 'text') text += event.content
  }
  const frame = (id, type, events) => `id: ${id}\ndata: ${JSON.stringify({ type, events })}\n\n`
  const initial = frame(10, 'run_snapshot', [{ type: 'text', content: '前' }])
  const batch = frame(13, 'run_delta', [{ type: 'text', content: '中' }, { type: 'text', content: '后' }])
  await readAgentStream(response(initial + batch), state, handle)
  await readAgentStream(response(batch + frame(14, 'run_delta', [{ type: 'stream_end' }])), state, handle)
  assert.equal(text, '前中后')
  assert.equal(state.lastEventId, 14)
  assert.equal(state.streamEnded, true)
})

test('new snapshots replace earlier output without duplicating text or usage', async () => {
  const state = {}
  let content = ''
  let tokens = 0
  const handle = event => {
    if (event.type === 'snapshot_reset') { content = ''; tokens = 0 }
    if (event.type === 'text') content += event.content
    if (event.type === 'usage') tokens += event.usage.output_tokens
  }
  const frame = (revision, text, ended = false) => `id: ${revision}\ndata: ${JSON.stringify({
    type: 'run_snapshot', revision, events: [
      { type: 'text', content: text }, { type: 'usage', usage: { output_tokens: 10 } },
      ...(ended ? [{ type: 'stream_end' }] : []),
    ],
  })}\n\n`
  await readAgentStream(response(frame(10, '前半段')), state, handle)
  assert.equal(content, '前半段')
  await readAgentStream(response(frame(10, '前半段') + frame(500, '前半段后半段', true)), state, handle)
  assert.equal(content, '前半段后半段')
  assert.equal(tokens, 10)
  assert.equal(state.lastEventId, 500)
  assert.equal(state.streamEnded, true)
})
