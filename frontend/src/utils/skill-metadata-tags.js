export const parseSkillMetadataTags = value => [...new Set(
  String(value || '').split(/[,，;；\r\n]+/).map(tag => tag.trim()).filter(Boolean),
)]

export const addSkillMetadataTags = (value, addition) => [...new Set([
  ...parseSkillMetadataTags(value), ...parseSkillMetadataTags(addition),
])].join(',')
