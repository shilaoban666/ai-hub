// Catalog sources and workspace connections have different IDs. Join only by
// source_mcp_service_id so equally named services remain independent.
export const buildMcpCatalog = (sources, connections) => {
  const cards = new Map()
  for (const source of sources) {
    const key = `source-${source.id}`
    const previous = cards.get(key)
    const origins = [...new Set([...(previous?.origins || []), ...(source.origins || [])])]
    cards.set(key, {
      ...previous,
      ...source,
      key,
      source_id: source.id,
      transport_type: source.type,
      origins,
      picker_source: origins.includes('mine') ? 'mine' : 'public',
      connection: null,
    })
  }
  for (const connection of connections) {
    const sourceId = connection.source_mcp_service_id
    const key = sourceId ? `source-${sourceId}` : `connection-${connection.id}`
    const source = cards.get(key)
    cards.set(key, {
      ...source,
      key,
      source_id: sourceId || null,
      name: connection.name,
      description: source?.description ?? connection.description,
      author: source?.author ?? connection.author,
      transport_type: connection.transport_type,
      origins: [...new Set([...(source?.origins || []), ...(connection.origins || [])])],
      connection,
    })
  }
  return [...cards.values()]
}

export const filterMcpCatalog = (cards, { view = 'all', source = 'all', query = '' } = {}) => {
  const keyword = query.trim().toLocaleLowerCase()
  return cards.filter(card => {
    if (view === 'connected' && !card.connection) return false
    if (source === 'system_default') {
      if (!card.connection?.is_system) return false
    } else if (source !== 'all' && !card.origins.includes(source)) return false
    return !keyword || [card.name, card.author, card.description, card.transport_type, card.tags]
      .some(value => String(value ?? '').toLocaleLowerCase().includes(keyword))
  })
}

const loadSourcePages = async (api, origin) => {
  const resources = []
  const limit = 100
  let skip = 0
  while (true) {
    const result = await api.getList({ skip, limit })
    const rows = result?.items || []
    for (const row of rows) {
      // Configuration and credentials are only read when connecting, never
      // retained by catalog cards or displayed in the details dialog.
      const { id, name, description, author, cover, type, tags, usage_instructions } = row
      resources.push({
        id, name, description, author, cover, type, tags, usage_instructions,
        origins: origin === 'mine' && row.is_public ? ['mine', 'public'] : [origin],
      })
    }
    skip += rows.length
    if (!rows.length || (result.total != null ? skip >= result.total : rows.length < limit)) break
  }
  return resources
}

export const loadMcpCatalogSources = async ({ mineApi, publicApi, systemMode = false, readOnly = false }) => {
  // A shared agent shows its owner's connected resources, never the visitor's
  // personal catalog. The scoped connections API enforces visibility.
  if (readOnly) return []
  const pages = await Promise.all([
    ...(systemMode ? [] : [loadSourcePages(mineApi, 'mine')]),
    loadSourcePages(publicApi, 'public'),
  ])
  return pages.flat()
}
