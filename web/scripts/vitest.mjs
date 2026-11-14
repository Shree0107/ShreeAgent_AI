// Runs Vitest with a normalised working directory.
//
// On Windows a lower-case drive letter in the current directory ("c:\..." instead of "C:\...", which some
// terminals produce) makes Node load Vitest twice under two different paths, and every test then fails
// with "Vitest failed to find the current suite". Upper-casing the drive letter before starting avoids it.
import { spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import process from 'node:process'

const cwd = process.cwd().replace(/^([a-z]):/, (_, d) => `${d.toUpperCase()}:`)
process.chdir(cwd)
const require = createRequire(`${cwd}/package.json`)
const bin = join(dirname(require.resolve('vitest/package.json')), 'vitest.mjs')
const r = spawnSync(process.execPath, [bin, ...process.argv.slice(2)], { stdio: 'inherit', cwd })
process.exit(r.status ?? 1)
