import assert from 'node:assert/strict'
import test from 'node:test'
import { buildMcpCatalog, filterMcpCatalog, loadMcpCatalogSources } from '../src/utils/mcp-catalog.js'

const sources = [
  { id: 1, name: 'Knowledge', author: '作者甲', type: 'http', origins: ['mine', 'public'] },
  { id: 2, name: 'Knowledge', author: '作者乙', type: 'stdio', origins: ['public'] },
]
const connections = [
  { id: 'system-11', definition_id: 11, source_mcp_service_id: 1, name: 'Knowledge', author: '旧作者', transport_type: 'http', status: 'active', is_system: true, origins: ['mine', 'public'] },
  { id: 12, definition_id: 13, source_mcp_service_id: 3, name: '已隐藏的资源', transport_type: 'sse', status: 'disabled', origins: ['mine'] },
  { id: 14, definition_id: 15, name: 'Knowledge', transport_type: 'http', status: 'active', origins: ['mine'] },
]

test('catalog joins connections by source ID and keeps equally named connectors independent', () => {
  const cards = buildMcpCatalog(sources, connections)
  assert.equal(cards.length, 4)
  assert.equal(cards.find(card => card.source_id === 1).connection.id, 'system-11')
  assert.equal(cards.find(card => card.source_id === 1).author, '作者甲')
  assert.equal(cards.find(card => card.source_id === 2).connection, null)
  assert.equal(cards.find(card => card.key === 'connection-14').connection.id, 14)
})

test('owned public catalog entries appear once, retain both sources, and connect using the owner API', () => {
  const cards = buildMcpCatalog([
    { ...sources[0], origins: ['mine'] },
    { ...sources[0], origins: ['public'] },
  ], [])
  assert.equal(cards.length, 1)
  assert.deepEqual(cards[0].origins, ['mine', 'public'])
  assert.equal(cards[0].picker_source, 'mine')
})

test('connected view includes disabled and no-longer-listed sources; filters compose with author search', () => {
  const cards = buildMcpCatalog(sources, connections)
  assert.equal(filterMcpCatalog(cards, { view: 'connected' }).length, 3)
  assert.deepEqual(filterMcpCatalog(cards, { source: 'public', query: ' 作者乙 ' }).map(card => card.source_id), [2])
  assert.deepEqual(filterMcpCatalog(cards, { view: 'connected', source: 'system_default' }).map(card => card.connection.id), ['system-11'])
  assert.equal(filterMcpCatalog(cards, { view: 'connected', query: '作者乙' }).length, 0)
})

test('disconnecting a listed source leaves a connectable card in all and removes it from connected', () => {
  const before = buildMcpCatalog(sources, [connections[0]])
  const after = buildMcpCatalog(sources, [])
  assert.equal(before.length, after.length)
  assert.equal(filterMcpCatalog(after, { view: 'connected' }).length, 0)
  assert.equal(after[0].source_id, 1)
  assert.equal(after[0].connection, null)
})

test('catalog reads all pages and does not retain configuration or credentials', async () => {
  const calls = []
  const rows = Array.from({ length: 103 }, (_, i) => ({
    id: i + 1, name: `Resource ${i}`, type: 'http', is_public: true,
    config: '{"headers":{"Authorization":"source-secret"}}',
  }))
  const result = await loadMcpCatalogSources({
    mineApi: { getList: async ({ skip, limit }) => {
      calls.push(skip)
      return { total: rows.length, items: rows.slice(skip, skip + limit) }
    } },
    publicApi: { getList: async () => ({ total: 0, items: [] }) },
  })
  assert.equal(result.length, 103)
  assert.deepEqual(calls, [0, 100])
  assert.deepEqual(result[0].origins, ['mine', 'public'])
  assert.equal(JSON.stringify(result).includes('source-secret'), false)
})

test('system catalog lists public sources only', async () => {
  const rows = await loadMcpCatalogSources({
    systemMode: true,
    mineApi: { getList: () => assert.fail('System defaults cannot import private resources') },
    publicApi: { getList: async () => ({ total: 1, items: [sources[1]] }) },
  })
  assert.deepEqual(rows.map(row => row.id), [2])
  assert.deepEqual(rows[0].origins, ['public'])
})

test('shared agent catalog never fetches the visitor personal or public catalog', async () => {
  const api = { getList: () => assert.fail('Only scoped agent connections should be visible') }
  assert.deepEqual(await loadMcpCatalogSources({ readOnly: true, mineApi: api, publicApi: api }), [])
})
