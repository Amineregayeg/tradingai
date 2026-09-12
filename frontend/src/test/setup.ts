import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock IntersectionObserver (used by some components)
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock WebSocket
global.WebSocket = vi.fn().mockImplementation(() => ({
  send: vi.fn(),
  close: vi.fn(),
  addEventListener: vi.fn(),
  removeEventListener: vi.fn(),
  readyState: 1,
})) as unknown as typeof WebSocket

// =====================================================================================
// T-0142 / B421 — THE FIX, AND A REGRESSION GUARD FOR DOM ACCUMULATION
// =====================================================================================
//
// **`@testing-library/react` REGISTERS ITS `afterEach(cleanup)` AT IMPORT TIME**
// (`dist/index.js:23-29`, guarded by `typeof afterEach === 'function'`). A `node_modules`
// dependency is cached for the life of the PROCESS, so when every test file shares one process
// that hook is installed in the **first file's** suite context only. **Every later file gets no
// cleanup and accumulates its own renders.** Measured:
//
//   isolation           every test starts with an empty body, in every file
//   one process         FILE1 fine. FILE2's second test STARTS with the first test's render
//                       still mounted, and ends with two copies.
//
// It presents as `Found multiple elements with the role ...` in a file that renders more than
// once — a failure that looks like a bug in the test.
//
// **THIS FILE IS THE RIGHT PLACE BECAUSE OUR OWN SOURCE RE-EXECUTES PER TEST FILE** — measured
// two ways: a counter here resets for each file, and a local module's id differs per file while a
// `node_modules` module's is inherited. Only externalised dependencies are cached. So registering
// cleanup here runs it for every file, which is exactly what the import-time hook fails to do.
//
// Evidence and the full sequence — including the three detectors that turned out inert and the
// three mechanisms that turned out false: `agents/tasks/T-0142/_runs/EVIDENCE.md`.
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})

// **THE GUARD. IT WATCHES DOM ACCUMULATION AND NOTHING WIDER — the name says so on purpose.**
//
// It cannot see a leaked clipboard stub, and `@testing-library/user-event` has two module-scope
// registrations with the identical defect (`Clipboard.js:156-162`) that are latent only because
// nothing here touches the clipboard. **DOM accumulation and clipboard state are different
// artefacts of one cause**, so the class is recorded in the register rather than guarded here. An
// "environment is pristine" assertion covering only the axes we thought of is how three inert
// detectors got written.
//
// ⚠ **QUIET IS NOT INERT.** With the cleanup above in place this can fire only if that cleanup is
// removed or a new uncovered registration appears — which is a regression guard working, not a
// dead arm. This task deleted three arms for being inert; do not make this the fourth.
beforeEach(() => {
  const leftover = document.body.innerHTML
  if (leftover === '') return

  throw new Error(
    [
      `DOM ACCUMULATION — this test started with markup left over from the previous one.`,
      ``,
      `  ${leftover.length} bytes already in document.body`,
      `  ${document.body.innerHTML.slice(0, 120)}`,
      ``,
      `An assertion of PRESENCE can now be satisfied by the PREVIOUS test's render, so a test can`,
      `pass having rendered nothing relevant. Absence assertions and getByRole fail loudly; that`,
      `direction is the safe one.`,
      ``,
      `TWO CAUSES, and the second is the likely one:`,
      `  1. the afterEach(cleanup) in src/test/setup.ts was removed or is throwing`,
      `  2. this run shares ONE PROCESS across test files (--pool=forks with singleFork, or`,
      `     --poolOptions.*.isolate=false). @testing-library/react registers its cleanup hook at`,
      `     IMPORT time, and a node_modules module is cached per PROCESS — so in a shared process`,
      `     only the FIRST file gets that hook.`,
      ``,
      `NOTE: isolate:true does NOT prevent cause 2 — measured, including with isolate set`,
      `explicitly on the CLI. isolate recycles a worker after each test; singleFork decides how`,
      `many workers exist. Orthogonal. Do not "fix" this by pinning isolate.`,
      ``,
      `IF YOU ARE HERE BECAUSE THE FULL RUN GETS OOM-KILLED: singleFork is a DIAGNOSTIC TOOL and`,
      `its numbers are quarantined. Run chunked instead, two files at a time, normal isolation:`,
      `  npx vitest run <fileA> <fileB> > batch1.log 2>&1`,
      `then verify the union — each file in exactly one log, every exit code read.`,
      ``,
      `agents/tasks/T-0142/_runs/EVIDENCE.md`,
    ].join('\n'),
  )
})
