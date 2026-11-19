// Checks that every locale file in frontend/src/locales/ matches the English texts actually
// in use:
// - every t('...') key in the frontend has a translation in each locale (warning only, see below)
// - every error message the backend returns ({"error": "..."}) has one too, since the
//   frontend shows those through t(data.error) (warning only)
// - the locale files have no leftover keys that nothing uses anymore
// - no new user-visible English bypasses t() (heuristic, see untranslatedPatterns)
// - each translation ends with the same punctuation as its English text
// Keys are the exact English text, so a changed English string silently falls back to
// English without this check. Run from the repo root: node scripts/check-translations.mjs
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'

const root = process.cwd()
const frontendSrc = join(root, 'frontend/src')
const backendDir = join(root, 'backend')
// every locale must cover the same key set; missing translations are warnings (the app
// shows English until a maintainer adds them), everything else is a hard problem
const locales = [
  { file: 'nl.js', name: 'Dutch' },
  { file: 'it.js', name: 'Italian' },
]

function walk(dir, accept, skip = () => false) {
  const found = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) {
      if (!skip(name)) found.push(...walk(path, accept, skip))
    } else if (accept(name)) found.push(path)
  }
  return found
}

const stringLiteral = /'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g
const parseLiteral = (literal) => new Function(`return ${literal}`)()

// first argument of t(...): a string literal, or a ternary between string literals
const frontendKeys = new Set()
const tCall = /\bt\(\s*((?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|[^,()'"])*)/g
for (const file of walk(frontendSrc, (name) => /\.jsx?$/.test(name), (name) => name === 'locales')) {
  const code = readFileSync(file, 'utf8')
  for (const call of code.matchAll(tCall)) {
    for (const literal of call[1].matchAll(stringLiteral)) frontendKeys.add(parseLiteral(literal[0]))
  }
  // option labels in these files are passed to t() as variables (t(option.label), t(preset.name))
  if (/formOptions|themePresets/.test(file)) {
    for (const match of code.matchAll(/\b(?:label|name):\s*('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")/g)) {
      frontendKeys.add(parseLiteral(match[1]))
    }
  }
}

// "error": "..." literals, and "error": f"..." f-strings: those can't be looked up as-is, so
// the frontend rebuilds them from a t() template whose {placeholders} are named like the
// Python variables (e.g. {minutes_left}), which makes the f-string text the template key
const backendErrors = new Set()
const backendTemplates = new Set()
for (const file of walk(backendDir, (name) => name.endsWith('.py') && !name.startsWith('test_'), (name) =>
  ['.venv', 'migrations', '__pycache__', 'instance'].includes(name),
)) {
  for (const match of readFileSync(file, 'utf8').matchAll(/"error":\s*(f?)"((?:\\.|[^"\\])*)"/g)) {
    ;(match[1] ? backendTemplates : backendErrors).add(match[2])
  }
}

// Heuristic for English that skips t() altogether: literal text in JSX, in user-visible
// attributes, or in alert/confirm/prompt/error state. Add `// i18n-ignore` to a line (or the
// line above) for intentional exceptions.
const untranslatedPatterns = [
  // text between tags on one line: <h3>Some text</h3>, <Icon /> Some text ('=>' is not a tag)
  /(?<!=)>\s*([A-Za-z][^<>{}]*[A-Za-z.!?…])\s*(?:<|$)/,
  // a line that is only text (multi-line JSX children)
  /^\s*([A-Z][A-Za-z0-9 ,.'’!?…:;()&-]*[A-Za-z.!?…)])\s*$/,
  // user-visible attributes with a literal value (URLs excepted)
  /\b(?:title|aria-label|placeholder|alt|label)="(?!https?:)([^"]*[A-Za-z][^"]*)"/,
  // literal strings shown through browser dialogs or error state
  /\b(?:alert|confirm|prompt|set\w*Error)\(\s*(['"`])([^'"`]*[A-Za-z][^'"`]*)\1/,
]
const untranslated = []
for (const file of walk(frontendSrc, (name) => name.endsWith('.jsx'), (name) => name === 'locales')) {
  const lines = readFileSync(file, 'utf8').split('\n')
  lines.forEach((line, index) => {
    if (/^\s*(\/\/|\*|\/\*)/.test(line)) return
    if (line.includes('i18n-ignore') || lines[index - 1]?.includes('i18n-ignore')) return
    if (untranslatedPatterns.some((pattern) => pattern.test(line))) {
      untranslated.push(`not translated (wrap it in t()): ${file.slice(root.length + 1)}:${index + 1}: ${line.trim()}`)
    }
  })
}

// problems fail the check; warnings don't. A missing translation is only a warning so
// contributors who don't speak the language aren't blocked: the app shows English until a
// maintainer adds the translation. Everything else can be fixed without knowing the language.
// a translation ends with the same punctuation as the English text (or with none, if it has none)
const ending = (text) => (/[.?!:…]$/.exec(text.trim()) ?? ['nothing'])[0]
const problems = [...untranslated]
const warnings = []
const summaries = []
for (const { file, name } of locales) {
  const dictionary = (await import(pathToFileURL(join(frontendSrc, 'locales', file)).href)).default
  const keys = new Set(Object.keys(dictionary))
  const localeWarnings = []
  for (const key of frontendKeys) if (!keys.has(key)) localeWarnings.push(`missing ${name} translation in ${file}: ${key}`)
  for (const error of backendErrors) {
    if (!keys.has(error)) localeWarnings.push(`missing ${name} translation in ${file} (backend error): ${error}`)
  }
  for (const key of keys) {
    if (!frontendKeys.has(key) && !backendErrors.has(key)) problems.push(`unused in ${file}: ${key}`)
  }
  // a translation ends with the same punctuation as the English text (or with none, if it has none)
  for (const [key, value] of Object.entries(dictionary)) {
    if (ending(key) !== ending(value)) {
      problems.push(`punctuation differs (English ends with ${ending(key)}, ${name} with ${ending(value)}): ${key}`)
    }
  }
  warnings.push(...localeWarnings)
  summaries.push(
    `${file} OK: ${frontendKeys.size} frontend texts, ${backendErrors.size} backend errors and ` +
      `${backendTemplates.size} backend error template(s) checked, ${localeWarnings.length} ${name} translation(s) missing`,
  )
}
for (const template of backendTemplates) {
  if (!frontendKeys.has(template)) {
    problems.push(`backend f-string error has no matching t() template in the frontend: ${template}`)
  }
}

// in GitHub Actions, warnings become annotations on the pull request
const annotate = process.env.GITHUB_ACTIONS === 'true'
for (const warning of warnings) console.log(annotate ? `::warning title=Translation::${warning}` : `warning: ${warning}`)

if (problems.length > 0) {
  console.error(problems.join('\n'))
  process.exit(1)
}
console.log(summaries.join('\n'))
