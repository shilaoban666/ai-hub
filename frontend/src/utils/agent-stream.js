// Event IDs acknowledge complete frames only, so reconnecting cannot duplicate
// text or lose a frame split across network packets.
export async function readAgentStream(response, state, onEvent) {
  if (!response.body) throw new Error('后端未返回流式响应')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() || ''
      for (const frame of frames) {
        const lines = frame.split(/\r?\n/)
        const data = lines.find(line => line.startsWith('data: '))
        if (!data) continue
        const idLine = lines.find(line => line.startsWith('id: '))
        const id = idLine ? Number(idLine.slice(4)) : 0
        if (id && id <= (state.lastEventId || 0)) continue
        const event = JSON.parse(data.slice(6))
        const events = event.type === 'run_snapshot'
          ? [{ type: 'snapshot_reset' }, ...event.events, { type: 'snapshot_applied' }]
          : event.type === 'run_delta' ? event.events : [event]
        for (const item of events) {
          onEvent(item)
          if (item.type === 'stream_end') state.streamEnded = true
        }
        if (id) state.lastEventId = id
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
