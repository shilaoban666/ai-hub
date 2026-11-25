import { readFile, writeFile } from 'node:fs/promises'

const root = new URL('../', import.meta.url)
const scriptPath = new URL('public/embed/assistant.js', root)
let script = (await readFile(scriptPath, 'utf8')).replaceAll('\r\n', '\n')
for (const name of ['cow', 'sprout']) {
  const svg = (await readFile(new URL(`public/characters/${name}-motion-v1.svg`, root), 'utf8')).replaceAll('\r\n', '\n')
  const pattern = new RegExp(`  var ${name}Markup = [^\\n]*`)
  if (!pattern.test(script)) throw new Error(`Missing ${name} markup slot`)
  script = script.replace(pattern, () => `  var ${name}Markup = ${JSON.stringify(svg)}`)
  const still = svg.replace(/<style>[\s\S]*?<\/style>/, '').replace(' id="hello"', '')
  await writeFile(new URL(`public/characters/${name}-v1.svg`, root), still)
  if (name === 'cow') await writeFile(new URL('public/embed/icons/assistant-core.svg', root), svg)
}
await writeFile(scriptPath, script)
