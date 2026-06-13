export const meta = {
  name: 'v5-execution-orchestrator',
  description: 'Execute v5 remediation phases sequentially with per-phase Done-when verification gates, one corrective retry, and per-phase commits',
  whenToUse: 'Run the full v5 bug & quality remediation: 10 phase specs, one Opus subagent each, strict dependency-ordered, verified and committed phase by phase.',
  phases: [
    { title: 'Implement', detail: 'one Opus subagent per phase spec', model: 'opus' },
    { title: 'Verify', detail: 'orchestrator critically checks Done-when + runs tests', model: 'opus' },
  ],
}

// ── Constants ────────────────────────────────────────────────────────────────
const REPO = '/Users/adviklall/Documents/projects LOCAL/persFin app/Personal-FinanceAPP'
const DOCS = `${REPO}/docs/v5 execution`

// Execution order: numeric, EXCEPT 10 is pulled forward to run right after 03
// (README hard-dep: 03 removes user_id from /plaid/link-token/; 10 fixes the
// client fetchLinkToken that still sends it — Plaid connect is broken between).
const ORDER = [
  { id: '01', file: '01-single-user-invariant.md' },
  { id: '02', file: '02-ratelimit-cost-infra.md' },
  { id: '03', file: '03-plaid-auth-and-llm-caps.md' },
  { id: '10', file: '10-client-correctness.md' },
  { id: '04', file: '04-assistant-action-safety.md' },
  { id: '05', file: '05-mcp-hardening.md' },
  { id: '06', file: '06-money-correctness.md' },
  { id: '07', file: '07-auth-hardening.md' },
  { id: '08', file: '08-plaid-integrity.md' },
  { id: '09', file: '09-game-substrate-integrity.md' },
]

// Cross-phase hard-dependency facts every agent must respect (from README.md).
const GLOBAL_RULES = `
PROJECT: Personal finance app (FastAPI server + React/TS client) at:
  ${REPO}
This local tree IS a git repo, currently on branch v10. Run tests ONLY in this
tree (never against OneDrive node_modules).

TEST COMMANDS (run from ${REPO}):
  - Server: .venv/bin/pytest -q
  - Client: node_modules/.bin/vitest run
  Targeted runs (faster) are fine while iterating, but the phase is NOT done
  until the FULL relevant suite is green.

SINGLE-USER APP. There is exactly one real user; shared XP/streak/boss/Category
state is CORRECT, not a leak. Do not add per-user keys to the game substrate.

CROSS-PHASE HARD DEPENDENCIES (do not violate):
  - 02 slowapi gotcha: the limiter's \`enabled\` is FIXED at construction. Tests
    must flip \`limiter.enabled\` (the instance), NEVER settings.rate_limit_enabled
    at runtime. (single_user in step 01 is different — it IS read fresh from
    settings each request, so monkeypatch reaches it.)
  - 03 token-source: the streaming chat path exposes NO token count
    (astream_events v2). The LLM budget hard cap is REQUESTS/DAY, not tokens. A
    token cap is advisory only — never ship a token cap that meters 0.
  - 03 -> 10: step 03 removes the user_id param from /plaid/link-token/; the
    client fetchLinkToken (store.ts ~697) must use the authed no-param endpoint.
    These two MUST both be correct together (10 runs right after 03 here).
  - 06 <-> 08 transfer guard: step 06's transfer guard is name-keyed; step 08
    de-name-keys Plaid and MUST update that guard, or a renamed Plaid account is
    mis-classified as manual and a transfer double-counts on next sync. They are
    run back-to-back (06 then 08) in this run — preserve the coupling.
  - Single-worker invariant (02, 05, 09): the slowapi limiter, MCP throttles, and
    the APScheduler are in-process per-worker. >1 worker multiplies limits /
    double-fires jobs. Must run ONE worker until Redis + leader election exist —
    enforce at startup / document in deploy.
  - 05 caveat: stateless_http support in the installed fastmcp is NOT verified —
    verify before relying on it; degrade gracefully if absent.
  - 07 precondition: before removing refresh_token from response bodies, grep
    client/src for refresh_token and migrate any usage to the cookie.
`.trim()

// ── Schemas ──────────────────────────────────────────────────────────────────
const IMPL_SCHEMA = {
  type: 'object',
  required: ['summary', 'files_changed', 'done_when_self_report', 'server_tests', 'client_tests', 'open_concerns'],
  additionalProperties: false,
  properties: {
    summary: { type: 'string', description: 'What was implemented, in 3-8 sentences.' },
    files_changed: {
      type: 'array',
      items: { type: 'string' },
      description: 'Repo-relative paths of every file created or modified.',
    },
    done_when_self_report: {
      type: 'array',
      description: 'Each Done-when checklist item from the phase spec, with the agent\'s self-assessed status and evidence.',
      items: {
        type: 'object',
        required: ['item', 'status', 'evidence'],
        additionalProperties: false,
        properties: {
          item: { type: 'string' },
          status: { type: 'string', enum: ['done', 'partial', 'deferred', 'not_done'] },
          evidence: { type: 'string', description: 'File:line or test name proving it.' },
        },
      },
    },
    server_tests: { type: 'string', description: 'Exact pytest command run and the PASS/FAIL tail (counts).' },
    client_tests: { type: 'string', description: 'Exact vitest command run and the PASS/FAIL tail, or "n/a — no client changes".' },
    open_concerns: { type: 'string', description: 'Anything unresolved, deferred (with reason), or risky for later phases. "none" if clean.' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdict', 'done_when_check', 'test_evidence_ok', 'edge_cases_checked', 'reasons', 'fix_instructions'],
  additionalProperties: false,
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'], description: 'pass only if EVERY non-deferred Done-when item is genuinely satisfied AND tests are green.' },
    done_when_check: {
      type: 'array',
      description: 'Independent re-verification of each Done-when item by reading the actual code/tests — not trusting the implementer\'s self-report.',
      items: {
        type: 'object',
        required: ['item', 'satisfied', 'evidence'],
        additionalProperties: false,
        properties: {
          item: { type: 'string' },
          satisfied: { type: 'boolean' },
          evidence: { type: 'string', description: 'What you actually read/ran to confirm. Cite file:line or test output.' },
        },
      },
    },
    test_evidence_ok: { type: 'boolean', description: 'You re-ran the tests yourself (or confirmed the run) and they are actually green — not just trusting the report.' },
    edge_cases_checked: { type: 'string', description: 'Edge cases / cross-phase regressions you specifically verified (e.g. did 06 leave the transfer guard in a shape 08 can update; did 03+10 keep Plaid connect working).' },
    reasons: { type: 'string', description: 'Concise justification of the verdict.' },
    fix_instructions: { type: 'string', description: 'If fail: precise, actionable instructions for the corrective retry. "" if pass.' },
  },
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function implPrompt(phase, priorContext, retryNote) {
  return `${GLOBAL_RULES}

You are implementing ONE phase of the v5 remediation. Work at HIGH effort and be
thorough and surgical — production code changes in a real repo.

PHASE SPEC TO IMPLEMENT: ${DOCS}/${phase.file}
Read that file in full FIRST. It is self-contained: Goal, Implementation, Tests
to add, User-centric & edge-case checks, Regression guardrails, and a Done-when
checklist. Implement EVERYTHING in it.

CONTEXT FROM PRIOR PHASES ALREADY COMPLETED IN THIS RUN:
${priorContext || '(this is the first phase — nothing done yet)'}
${retryNote ? `\n!!! CORRECTIVE RETRY — your previous attempt FAILED verification. Fix exactly this:\n${retryNote}\n` : ''}
RULES:
- Implement the code AND the tests the spec calls for.
- Run the relevant test suite(s) yourself and get them GREEN before finishing.
  Server: .venv/bin/pytest -q   |   Client: node_modules/.bin/vitest run
  (Run from ${REPO}.) Do NOT skip, xfail, or delete tests to make them pass.
- If the spec marks something as deferred / product-decision (e.g. step 04 Part
  B), you may defer it — but report it explicitly as deferred, and ensure the
  deferred path is dead-but-safe.
- Do NOT git commit — the orchestrator handles commits after verification.
- Stay within this phase's scope; do not pull work forward from later phases.
Return the structured result.`
}

function verifyPrompt(phase, impl) {
  return `${GLOBAL_RULES}

You are the VERIFICATION GATE for one phase of the v5 remediation. Be adversarial
and skeptical. Your job is to INDEPENDENTLY confirm the phase is correctly
implemented before the next phase builds on it. Do NOT trust the implementer's
self-report — read the actual code and re-run the tests.

PHASE SPEC: ${DOCS}/${phase.file}
Read the spec's "Done-when", "User-centric & edge-case checks", and "Regression
guardrails" sections.

THE IMPLEMENTER REPORTED:
${JSON.stringify(impl, null, 2)}

DO THIS:
1. Read each file the implementer changed and confirm the change actually matches
   the spec's Implementation section (not just that *a* change exists).
2. For EACH Done-when item, independently verify it by reading code / tests.
   Mark satisfied=false if you cannot prove it.
3. Re-run the relevant suites yourself from ${REPO}:
     Server: .venv/bin/pytest -q
     Client: node_modules/.bin/vitest run  (only if client changed)
   Confirm they are GREEN. If the implementer claimed green but they are not,
   that is an automatic FAIL.
4. Check the edge cases the spec lists, AND the cross-phase hard-dependencies in
   GLOBAL_RULES that this phase touches (e.g. 02 slowapi gotcha, 03/10 Plaid,
   06->08 transfer guard, single-worker invariant). A change that satisfies the
   letter of Done-when but breaks a cross-phase contract is a FAIL.
5. Confirm no tests were skipped/xfailed/deleted to fake green.

Verdict = pass ONLY if every non-deferred Done-when item is genuinely satisfied
and the suites are actually green. Otherwise fail, with precise fix_instructions
for a single corrective retry. Return the structured result.`
}

// Compact rolling context handed to the next phase's implementer.
function digest(phase, impl, verdict) {
  const items = (verdict.done_when_check || [])
    .map(d => `    - [${d.satisfied ? 'x' : ' '}] ${d.item}`)
    .join('\n')
  return `PHASE ${phase.id} (${phase.file}) — VERIFIED PASS
  Summary: ${impl.summary}
  Files changed: ${(impl.files_changed || []).join(', ')}
  Done-when (independently confirmed):
${items}
  Open concerns carried forward: ${impl.open_concerns || 'none'}
  Edge cases verified: ${verdict.edge_cases_checked}`
}

// ── Run ──────────────────────────────────────────────────────────────────────
const completed = []        // digests of passed phases, in order
const results = []          // final report rows
let priorContext = ''

for (const step of ORDER) {
  log(`▶ Phase ${step.id} — ${step.file}`)

  let impl = null
  let verdict = null
  let retryNote = ''
  let attempts = 0

  // up to 2 attempts: initial + one corrective retry
  while (attempts < 2) {
    attempts++
    phase('Implement')
    impl = await agent(implPrompt(step, priorContext, retryNote), {
      label: `impl:${step.id}${attempts > 1 ? '(retry)' : ''}`,
      phase: 'Implement',
      model: 'opus',
      schema: IMPL_SCHEMA,
    })
    if (!impl) {
      verdict = { verdict: 'fail', reasons: 'implementer agent died/aborted', fix_instructions: '', done_when_check: [], test_evidence_ok: false, edge_cases_checked: '' }
      break
    }

    phase('Verify')
    verdict = await agent(verifyPrompt(step, impl), {
      label: `verify:${step.id}${attempts > 1 ? '(retry)' : ''}`,
      phase: 'Verify',
      model: 'opus',
      schema: VERDICT_SCHEMA,
    })
    if (!verdict) {
      verdict = { verdict: 'fail', reasons: 'verifier agent died/aborted', fix_instructions: 'Re-run verification.', done_when_check: [], test_evidence_ok: false, edge_cases_checked: '' }
    }

    if (verdict.verdict === 'pass') break

    if (attempts < 2) {
      retryNote = `${verdict.reasons}\n\nFIX INSTRUCTIONS:\n${verdict.fix_instructions}`
      log(`  ✗ Phase ${step.id} failed verification — issuing one corrective retry`)
    }
  }

  if (!verdict || verdict.verdict !== 'pass') {
    // HALT: do not build later phases on a broken base.
    log(`  ⛔ Phase ${step.id} still failing after retry — HALTING the run.`)
    results.push({ phase: step.id, file: step.file, status: 'FAILED — halted', attempts, reasons: verdict?.reasons || 'unknown', fix_instructions: verdict?.fix_instructions || '', impl_summary: impl?.summary || '' })
    return {
      halted: true,
      halted_at: step.id,
      completed: results,
      message: `Run halted at phase ${step.id} after a corrective retry still failed verification. Earlier phases are committed; this phase's partial changes are in the working tree, uncommitted, for your review.`,
    }
  }

  // Passed — commit this phase, then roll context forward.
  const filesList = (impl.files_changed || []).map(f => `  - ${f}`).join('\n')
  const commitResult = await agent(
    `In the git repo at ${REPO} (branch v10), stage ALL current changes and create
ONE commit for completed v5 phase ${step.id}.

Run, from ${REPO}:
  git add -A
  git commit  (with the message below)

Use this exact commit message (heredoc or -F -):
---
v5-${step.id}: ${step.file.replace(/^\d+-/, '').replace(/\.md$/, '').replace(/-/g, ' ')}

${impl.summary}

Files:
${filesList}

Verified: all Done-when items confirmed; suites green.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
---
Do NOT push. After committing, run \`git log --oneline -1\` and return its output
as plain text (the commit hash + subject). If there was nothing to commit, say so.`,
    { label: `commit:${step.id}`, phase: 'Verify', model: 'opus' }
  )

  log(`  ✓ Phase ${step.id} verified & committed: ${(commitResult || '').split('\n')[0]}`)

  const d = digest(step, impl, verdict)
  completed.push(d)
  priorContext = completed.join('\n\n')
  results.push({ phase: step.id, file: step.file, status: 'passed', attempts, commit: (commitResult || '').split('\n')[0], impl_summary: impl.summary })
}

return {
  halted: false,
  completed: results,
  message: `All ${ORDER.length} v5 phases implemented, independently verified against their Done-when checklists, and committed in order (01,02,03,10,04,05,06,07,08,09) on branch v10.`,
}
