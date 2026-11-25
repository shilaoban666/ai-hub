const SYSTEM_ARTIFACT_FILE_NAMES = new Set([
  'claude.md', 'agents.md', 'soul.md', 'identity.md', 'user.md', 'tools.md',
  '.mcp.json', 'hook_permission.log', 'hook.py', 'pre_tool_use.py', 'post_tool_use.py',
])

const SYSTEM_ARTIFACT_DIRECTORY_NAMES = new Set([
  '.claude', '.aihub', 'hooks', 'memory', 'skills',
])

const isSystemArtifactPath = path => {
  const segments = path.split('/').filter(Boolean).map(segment => segment.toLowerCase())
  const fileName = segments.at(-1)
  return SYSTEM_ARTIFACT_FILE_NAMES.has(fileName)
    || segments.some(segment => SYSTEM_ARTIFACT_DIRECTORY_NAMES.has(segment))
}

export const getChatArtifacts = (blocks = []) => {
  const files = new Map()
  for (const block of blocks) {
    if (block?.type !== 'artifacts' || !Array.isArray(block.files)) continue
    for (const file of block.files) {
      if (typeof file?.path !== 'string' || !file.path.trim()) continue
      const path = file.path.replaceAll('\\', '/')
      if (path.startsWith('/') || /^[a-z]:/i.test(path) || path.split('/').some(part => part === '..')) continue
      if (isSystemArtifactPath(path)) continue
      files.set(path, { ...file, path, name: file.name?.trim() || path.split('/').at(-1) })
    }
  }
  return [...files.values()]
}
