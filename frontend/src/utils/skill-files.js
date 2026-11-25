export const formatSkillFileSize = (file) => {
  const bytes = file?.is_binary
    ? Number(file.size ?? 0)
    : new TextEncoder().encode(String(file?.content ?? '')).length
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let size = bytes / 1024
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }
  return `${Number(size.toFixed(1))} ${units[unitIndex]}`
}

// After a successful save, later renames must reference the new stored paths.
export const syncSkillFilePaths = (nodes, parent = '') => {
  for (const node of nodes) {
    node.path = parent ? `${parent}/${node.label}` : node.label
    if (node.is_binary) node.original_path = node.path
    if (node.children) syncSkillFilePaths(node.children, node.path)
  }
}
