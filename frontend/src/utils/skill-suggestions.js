// Recommendations always come from the caller's available skills, without generating prompts.
export function buildSkillSuggestions(skills = []) {
  const seen = new Set()
  const suggestions = []
  for (const skill of skills) {
    const skillId = Number(skill.id)
    if (!Number.isSafeInteger(skillId) || skillId <= 0 || !Array.isArray(skill.conversation_examples)) continue
    for (const example of skill.conversation_examples) {
      if (typeof example !== 'string') continue
      const prompt = example.trim()
      const key = prompt.replace(/\s+/g, ' ').toLocaleLowerCase()
      if (!key || seen.has(key)) continue
      seen.add(key)
      suggestions.push({ key, skillId, skillName: skill.name?.trim() || '无', prompt })
    }
  }
  return suggestions
}

export function pickSkillSuggestions(pool, previous = [], random = Math.random) {
  const shuffled = [...pool]
  for (let index = shuffled.length - 1; index > 0; index--) {
    const other = Math.floor(random() * (index + 1))
    ;[shuffled[index], shuffled[other]] = [shuffled[other], shuffled[index]]
  }
  const previousKeys = new Set(previous.map(item => item.key))
  shuffled.sort((a, b) => Number(previousKeys.has(a.key)) - Number(previousKeys.has(b.key)))
  const selectedSkills = new Set()
  const result = []
  const extraExamples = []
  for (const suggestion of shuffled) {
    if (selectedSkills.has(suggestion.skillId)) {
      extraExamples.push(suggestion)
      continue
    }
    selectedSkills.add(suggestion.skillId)
    result.push(suggestion)
    if (result.length === 4) return result
  }
  return result.concat(extraExamples.slice(0, 4 - result.length))
}
