import request from './request'

const connectionPayload = (definition, agentId, credentialReferenceId, configOverrides = {}, authMode = 'manual') => ({
  definition_id: definition.id,
  revision_id: definition.latest_revision.id,
  name: definition.name,
  config_overrides: configOverrides,
  auth_mode: authMode,
  tool_policy: { risk_level: 'read', allowed_tools: [] },
  ...(credentialReferenceId ? { credential_reference_id: credentialReferenceId } : {}),
  ...(agentId ? { agent_id: agentId } : {}),
})

const connectDefinition = async (definition, agentId, credentialReferenceId, configOverrides = {}, authMode = 'manual') => {
  try {
    return await request.post('/assets/mcp/connections', connectionPayload(definition, agentId, credentialReferenceId, configOverrides, authMode))
  } catch (error) {
    if (!agentId) await request.delete(`/assets/mcp/definitions/${definition.id}`).catch(() => null)
    throw error
  }
}

const removeConnectedMcp = async connection => {
  await request.delete(`/assets/mcp/connections/${connection.id}`)
  await request.delete(`/assets/mcp/definitions/${connection.definition_id}`).catch(() => null)
}

export const assetsApi = {
  getImportStatus: params => request.get('/assets/import-status', { params }),
  getSkillCatalog: params => request.get('/assets/skills/catalog', { params }),
  getSkillCatalogReleases: id => request.get(`/assets/skills/catalog/${id}/releases`),
  getSkillInstallations: () => request.get('/assets/skills/installations'),
  getAvailableSkills: () => request.get('/assets/skills/available'),
  setSkillDevelopmentMode: (id, enabled, agentId) => request.put(`/assets/skills/${id}/development`, { enabled, ...(agentId ? { agent_id: agentId } : {}) }),
  getSkillDevelopmentFiles: id => request.get(`/assets/skills/${id}/development/files`),
  getSkillRelease: id => request.get(`/assets/skills/releases/${id}`),
  getSkillReleaseFiles: id => request.get(`/assets/skills/releases/${id}/files`),
  downloadSkillRelease: id => request.post(`/assets/skills/releases/${id}/download`, null, {
    responseType: 'blob', timeout: 120000,
  }),
  installSkill: data => request.post('/assets/skills/install', data),
  changeSkillRelease: (id, releaseId, agentId) => request.put(`/assets/skills/installations/${id}/release`, { release_id: releaseId, ...(agentId ? { agent_id: agentId } : {}) }),
  changeSkillLatest: (id, agentId) => request.put(`/assets/skills/installations/${id}/release`, { use_latest: true, ...(agentId ? { agent_id: agentId } : {}) }),
  uninstallSkill: id => request.delete(`/assets/skills/installations/${id}`),
  bindSkill: (installationId, agentId) => request.post(`/assets/skills/installations/${installationId}/bindings`, { agent_id: agentId }),
  unbindSkill: (installationId, agentId) => request.delete(`/assets/skills/installations/${installationId}/bindings/${agentId}`),
  getSystemSkillInstallations: () => request.get('/assets/admin/skills/defaults'),
  installSystemSkill: data => request.post('/assets/admin/skills/defaults', data),
  changeSystemSkillRelease: (id, releaseId) => request.put(`/assets/admin/skills/defaults/${id}/release`, { release_id: releaseId }),
  uninstallSystemSkill: id => request.delete(`/assets/admin/skills/defaults/${id}`),
  getSystemMcpDefinitions: () => request.get('/assets/admin/mcp/definitions'),
  getMcpDefinitions: () => request.get('/assets/mcp/definitions'),
  createSystemMcpDefinition: data => request.post('/assets/admin/mcp/definitions', data),
  getSystemPrompts: params => request.get('/assets/admin/prompts', { params }),
  createSystemPrompt: data => request.post('/assets/admin/prompts', data),
  updateSystemPrompt: (id, data) => request.put(`/assets/admin/prompts/${id}`, data),
  deleteSystemPrompt: id => request.delete(`/assets/admin/prompts/${id}`),

  listCredentials: () => request.get('/assets/credentials'),
  createCredential: data => request.post('/assets/credentials', data),
  addMcp: async data => connectDefinition(await request.post('/assets/mcp/definitions', data), data.agent_id, data.credential_reference_id),
  installMcp: async (sourceId, agentId, secrets, authMode = 'manual') => connectDefinition(
    await request.post('/assets/mcp/definitions/import', {
      source_mcp_service_id: sourceId,
      auth_mode: authMode,
      ...(agentId ? { agent_id: agentId } : {}),
      ...(secrets ? { secrets } : {}),
    }),
    agentId,
    undefined,
    secrets && Object.keys(secrets).length ? secrets : {},
    authMode,
  ),
  deleteMcpDefinition: id => request.delete(`/assets/mcp/definitions/${id}`),
  getMcpConnections: params => request.get('/assets/mcp/connections', { params }),
  connectMcpDefinition: (definition, agentId, credentialReferenceId) => request.post('/assets/mcp/connections', connectionPayload(definition, agentId, credentialReferenceId)),
  bindMcpConnection: (connectionId, agentId) => request.post(`/assets/mcp/connections/${connectionId}/bindings`, { agent_id: agentId }),
  unbindMcpConnection: (connectionId, agentId) => request.delete(`/assets/mcp/connections/${connectionId}/bindings/${agentId}`),
  getMcpHeaders: (resource, id, agentId) => request.get(`/assets/mcp/${resource}/${id}/headers`, { params: agentId ? { agent_id: agentId } : undefined }),
  getMcpSecrets: (resource, id, agentId) => request.get(`/assets/mcp/${resource}/${id}/secrets`, { params: agentId ? { agent_id: agentId } : undefined }),
  updateMcpSecrets: (resource, id, values, agentId) => request.put(
    `/assets/mcp/${resource}/${id}/secrets`,
    { values, ...(agentId ? { agent_id: agentId } : {}) },
  ),
  updateMcpHeaders: (resource, id, headers, authMode = 'manual', inheritSystem = false, agentId) => request.put(
    `/assets/mcp/${resource}/${id}/headers`,
    { headers, auth_mode: authMode, inherit_system: inheritSystem, ...(agentId ? { agent_id: agentId } : {}) },
  ),
  setMcpConnectionStatus: (id, status, agentId) => request.put(`/assets/mcp/connections/${id}/status`, { status, ...(agentId ? { agent_id: agentId } : {}) }),
  inspectMcpConnection: (id, agentId) => request.get(`/assets/mcp/connections/${id}/inspect`, { params: agentId ? { agent_id: agentId } : undefined, timeout: 30000 }),
  inspectSystemMcp: id => request.get(`/assets/mcp/definitions/${id}/inspect`, { timeout: 30000 }),
  removeMcp: removeConnectedMcp,

  getPromptCatalog: params => request.get('/assets/prompts/catalog', { params }),
  getWorkspacePrompts: params => request.get('/assets/prompts', { params }),
  removeWorkspacePrompt: id => request.delete(`/assets/prompts/${id}`),
  importPrompt: data => request.post('/assets/prompts/import', data),
  bindPrompt: (promptId, agentId, position = 0) => request.post(`/assets/prompts/${promptId}/bindings`, { agent_id: agentId, position }),
  unbindPrompt: (promptId, agentId) => request.delete(`/assets/prompts/${promptId}/bindings/${agentId}`),
}
