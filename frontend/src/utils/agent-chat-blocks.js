const findLatestUnresolved = (indexes, merged) => {
  for (let i = indexes.length - 1; i >= 0; i--) {
    const index = indexes[i]
    if (merged[index]?.type === 'tool_use' && merged[index].result === undefined) {
      return index
    }
  }
  return -1
}

const parseJsonContainer = (value) => {
  if (typeof value !== 'string') return value
  const source = value.trim()
  if (!source.startsWith('{') && !source.startsWith('[')) return null
  try {
    return JSON.parse(source)
  } catch {
    return null
  }
}

const HTML_RESULT_FIELDS = ['s_html', 'html']

export const extractToolResultHtml = (result) => {
  const root = parseJsonContainer(result)
  if (!root || typeof root !== 'object') return ''

  const seen = new Set()
  const findHtml = (value) => {
    const container = parseJsonContainer(value)
    if (!container || typeof container !== 'object' || seen.has(container)) return ''
    seen.add(container)

    if (!Array.isArray(container)) {
      for (const field of HTML_RESULT_FIELDS) {
        if (
          Object.prototype.hasOwnProperty.call(container, field)
          && typeof container[field] === 'string'
          && container[field].trim()
        ) {
          return container[field]
        }
      }
    }

    for (const child of Object.values(container)) {
      const html = findHtml(child)
      if (html) return html
    }
    return ''
  }

  return findHtml(root)
}

export const getToolResultHtml = (block, cache = null) => {
  if (!block || typeof block !== 'object') return ''
  if (typeof block.resultHtml === 'string') return block.resultHtml

  const cached = cache?.get(block)
  if (cached && cached.result === block.result) return cached.html

  const html = extractToolResultHtml(block.result)
  cache?.set(block, { result: block.result, html })
  return html
}

const PROCESS_BLOCK_TYPES = new Set(['thinking', 'tool_use'])

export const getToolResultSeverity = (result, isError = false) => {
  if (!isError) return ''
  const text = typeof result === 'string' ? result : JSON.stringify(result ?? '')
  // A hook failure alone is not a policy denial; require an explicit rejection message.
  const blocked = /\[workspace_isolation\]\s*拒绝\s*[:：]/i.test(text)
    || /^\s*(?:Error:\s*)?Permission to use [^\r\n]+ has been denied\b/i.test(text)
    || /^\s*(?:Error:\s*)?The user (?:doesn't|does not) want to proceed with this tool use\b/i.test(text)
  return blocked ? 'warning' : 'error'
}

export const hasRunningProcessBlocks = (blocks = []) => blocks.some(block => {
  if (block?.type === 'thinking') return !block.endTime
  if (block?.type === 'tool_use') return block.result === undefined && !block.endTime
  return false
})

export const groupProcessBlocks = (blocks = []) => {
  const segments = []
  let processBlocks = []
  let processStartIndex = -1

  const flushProcessBlocks = () => {
    if (processBlocks.length === 0) return
    segments.push({
      type: 'process_group',
      key: `process-${processStartIndex}`,
      blocks: processBlocks,
    })
    processBlocks = []
    processStartIndex = -1
  }

  blocks.forEach((block, index) => {
    // Invisible bookkeeping and whitespace must not split a continuous process.
    if (block?.type === 'usage' || (block?.type === 'text' && !String(block.content ?? '').trim())) return
    if (PROCESS_BLOCK_TYPES.has(block?.type)) {
      if (processBlocks.length === 0) processStartIndex = index
      processBlocks.push(block)
      return
    }

    flushProcessBlocks()
    segments.push({ type: 'block', key: `block-${index}`, block })
  })

  flushProcessBlocks()
  return segments
}

const normalizeBlock = (block) => {
  const normalized = { ...block }
  if (
    (normalized.type === 'thinking' || normalized.type === 'tool_use')
    && !normalized.endTime
  ) {
    normalized.endTime = normalized.startTime || 1
  }
  if (normalized.type === 'tool_use' && normalized.result !== undefined) {
    normalized.resultHtml = typeof normalized.resultHtml === 'string'
      ? normalized.resultHtml
      : extractToolResultHtml(normalized.result)
  }
  return normalized
}

export const mergeToolBlocks = (blocks = []) => {
  const merged = []
  const unresolvedToolIndexes = []
  const unresolvedById = new Map()

  for (const rawBlock of blocks) {
    const block = normalizeBlock(rawBlock)

    if (block.type === 'tool_use') {
      const index = merged.push(block) - 1
      unresolvedToolIndexes.push(index)
      if (block.tool_use_id) {
        const matchingIndexes = unresolvedById.get(block.tool_use_id) || []
        matchingIndexes.push(index)
        unresolvedById.set(block.tool_use_id, matchingIndexes)
      }
      continue
    }

    if (block.type !== 'tool_result') {
      merged.push(block)
      continue
    }

    const matchingIndexes = block.tool_use_id
      ? (unresolvedById.get(block.tool_use_id) || [])
      : unresolvedToolIndexes
    const toolIndex = findLatestUnresolved(matchingIndexes, merged)

    if (toolIndex >= 0) {
      merged[toolIndex] = normalizeBlock({
        ...merged[toolIndex],
        result: block.content ?? block.result ?? '',
        resultHtml: block.resultHtml,
        is_error: block.is_error,
        duration_ms: block.duration_ms ?? merged[toolIndex].duration_ms,
        endTime: block.endTime || merged[toolIndex].endTime,
      })
      continue
    }

    merged.push(normalizeBlock({
      type: 'tool_use',
      name: block.name || '工具',
      result: block.content ?? block.result ?? '',
      resultHtml: block.resultHtml,
      is_error: block.is_error,
      tool_use_id: block.tool_use_id,
      duration_ms: block.duration_ms,
      endTime: block.endTime,
    }))
  }

  return merged
}

// Keep one chronological trace for a whole reply, including calls separated by
// assistant text. The visible answer still renders its text blocks in order.
export const getProcessTrace = (blocks = []) => blocks.filter(block => PROCESS_BLOCK_TYPES.has(block?.type))

const concise = value => {
  const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : ''
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
}
const fileName = value => typeof value === 'string' ? concise(value.trim().split(/[\\/]/).pop()) : ''

const getToolActivity = block => {
  const input = block.input || {}
  const name = concise(block.name?.split('__').pop())
  let title = '正在调用工具'
  let detail = concise(input.description) || name
  switch (block.name) {
    case 'Agent': case 'Task': title = '正在执行子任务'; detail = concise(input.description) || concise(input.prompt); break
    case 'Read': title = '正在读取文件'; detail = fileName(input.file_path || input.path); break
    case 'Write': title = '正在写入文件'; detail = fileName(input.file_path || input.path); break
    case 'Edit': case 'MultiEdit': title = '正在修改文件'; detail = fileName(input.file_path || input.path); break
    case 'Bash': title = '正在执行命令'; detail = concise(input.description) || concise(input.command); break
    case 'Grep': title = '正在检索内容'; detail = concise(input.pattern); break
    case 'Glob': title = '正在查找文件'; detail = concise(input.pattern); break
    case 'Skill': title = '正在使用技能'; detail = concise(input.skill); break
    case 'WebSearch': title = '正在搜索资料'; detail = concise(input.query); break
    case 'WebFetch': title = '正在读取网页'; detail = concise(input.url); break
  }
  return { title, detail }
}

export const getRunActivity = (blocks = [], phase = 'running') => {
  const states = {
    connecting: '正在提交任务', queued: '正在排队等待执行',
    waiting_permission: '等待你确认下一步操作', stopping: '正在停止任务',
  }
  if (states[phase]) return { title: states[phase], detail: '', paused: ['queued', 'waiting_permission'].includes(phase) }

  // An earlier parallel call can still be running after a later one finishes.
  const active = blocks.filter(block => block?.type === 'tool_use' && block.result === undefined && !block.endTime)
  if (active.length) {
    const block = active[active.length - 1]
    let { title, detail } = getToolActivity(block)
    if (active.length > 1) {
      detail = `${title}${detail ? ` ${detail}` : ''}`
      title = `正在并行处理 ${active.length} 项任务`
    }
    return { title, detail, paused: false }
  }
  const latest = blocks.filter(block => ['thinking', 'text', 'tool_use'].includes(block?.type)).at(-1)
  if (latest?.type === 'thinking') {
    const content = concise(latest.content)
    return {
      title: latest.endTime ? (content || '思维链') : '思考中',
      detail: latest.endTime ? '' : content,
      paused: false,
    }
  }
  if (latest?.type === 'tool_use') {
    const { title, detail } = getToolActivity(latest)
    const severity = getToolResultSeverity(latest.result, latest.is_error)
    if (!severity) {
      return {
        title: title.replace(/^正在/, ''),
        detail: [detail, '已完成'].filter(Boolean).join(' '),
        paused: false,
      }
    }
    return {
      title: severity === 'warning' ? '调用被拦截' : '工具执行异常',
      detail: [title.replace(/^正在/, ''), detail].filter(Boolean).join(' '),
      paused: false,
    }
  }
  if (latest?.type === 'text' && concise(latest.content)) return { title: '正在生成回复', detail: '', paused: false }
  return { title: '正在等待模型响应', detail: '', paused: false }
}
