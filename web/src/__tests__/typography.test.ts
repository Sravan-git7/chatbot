import { existsSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Guards the two typography invariants that a browser cannot tell us about in a unit test:
 *  1. the font named in `--font-sans` is actually shipped with the app (before this was fixed, `Inter` was named first
 *     but no @font-face existed, so every user silently got a fallback font);
 *  2. the app stays self-contained: the strict CSP (`default-src 'self'`) means no webfont host may be referenced.
 */
const srcDir = join(process.cwd(), 'src')
const css = readFileSync(join(srcDir, 'index.css'), 'utf8')

const fontFaces = [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => m[1])
const sansStack = /--font-sans:\s*([^;]+);/.exec(css)?.[1] ?? ''

describe('typography', () => {
  it('declares the font family that the sans stack asks for', () => {
    expect(sansStack).toContain('"Inter Variable"')
    expect(fontFaces.length).toBeGreaterThan(0)
    for (const face of fontFaces) expect(face).toContain('"Inter Variable"')
  })

  it('ships every referenced font file with the app and never points at an external host', () => {
    const urls = fontFaces.flatMap((face) => [...face.matchAll(/url\(([^)]+)\)/g)].map((m) => m[1].replace(/['"]/g, '')))
    expect(urls.length).toBeGreaterThan(0)
    for (const url of urls) {
      expect(url).not.toMatch(/^https?:|^\/\//)
      const file = join(srcDir, url.replace(/^\.\//, ''))
      expect(existsSync(file), `${url} is referenced but not in web/src`).toBe(true)
      expect(statSync(file).size).toBeGreaterThan(1024)
    }
  })

  it('ships the font under its own license', () => {
    const license = join(srcDir, 'assets/fonts/LICENSE-inter-OFL.txt')
    expect(existsSync(license)).toBe(true)
    expect(readFileSync(license, 'utf8')).toMatch(/SIL Open Font License/)
  })

  it('keeps readable 16px answer text and a real heading/table hierarchy', () => {
    expect(css).toMatch(/--text-answer:\s*1rem/)
    expect(css).toMatch(/\.prose-chat\s*\{[^}]*font-size:\s*var\(--text-answer\)/)
    expect(css).toMatch(/\.prose-chat h2\s*\{/)
    expect(css).toMatch(/\.prose-chat table\s*\{/)
    expect(css).toMatch(/\.prose-chat\s*\{[^}]*text-wrap:\s*pretty/)
  })
})
