import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'))
const atLeast = (version: string, floor: number[]) => {
  const parts = version.split('.').map(Number)
  for (let i = 0; i < floor.length; i++) {
    if (parts[i] !== floor[i]) return parts[i] > floor[i]
  }
  return true
}

describe('dependency advisory regressions', () => {
  it('locks patched Vitest and mocker versions (GHSA-82fw-gwwq-j7x9)', () => {
    expect(atLeast(lock.packages['node_modules/vitest'].version, [4, 1, 11])).toBe(true)
    expect(atLeast(lock.packages['node_modules/@vitest/mocker'].version, [4, 1, 11])).toBe(true)
  })
  it('does not restore vulnerable Tinypool workers (GHSA-85c8-ppgw-ccpr)', () => {
    const pool = lock.packages['node_modules/tinypool']
    expect(pool === undefined || atLeast(pool.version, [2, 1, 2])).toBe(true)
  })
})
