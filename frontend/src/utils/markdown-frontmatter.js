/** Keep leading YAML metadata out of Markdown's Setext heading parser. */
export function markdownFrontmatter(md) {
  md.block.ruler.before('hr', 'skill_frontmatter', (state, startLine, endLine, silent) => {
    if (startLine !== 0 || state.level !== 0) return false
    const line = index => state.src.slice(state.bMarks[index], state.eMarks[index])
    if (!/^\uFEFF?---[ \t]*$/.test(line(0))) return false

    let closingLine = 1
    while (closingLine < endLine && !/^---[ \t]*$/.test(line(closingLine))) closingLine++
    if (closingLine === endLine) return false
    const content = state.src.slice(state.bMarks[1], state.bMarks[closingLine]).replace(/\n$/, '')
    // A horizontal rule followed by prose is still ordinary Markdown.
    if (!/^[A-Za-z_][\w-]*[ \t]*:/m.test(content)) return false
    if (silent) return true

    const token = state.push('skill_frontmatter', '', 0)
    token.block = true
    token.map = [0, closingLine + 1]
    token.content = content
    state.line = closingLine + 1
    return true
  })

  md.renderer.rules.skill_frontmatter = (tokens, index) =>
    `<pre class="skill-frontmatter"><code>${md.utils.escapeHtml(tokens[index].content)}</code></pre>\n`
}
