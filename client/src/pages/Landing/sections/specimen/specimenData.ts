import type { CSSProperties } from "react";

/**
 * THE SPECIMEN SHEET — content and geometry.
 *
 * A banknote prints the features that make it hard to forge and invites you to
 * check them. Real currency grades those features by HOW YOU VERIFY THEM:
 * Level 1 in the hand, Level 2 under a lamp or a UV light, Level 3 in a
 * laboratory. This sheet borrows the grading, and the grading is what makes it
 * honest — a mechanism that is real but needs a Postgres deployment, or one
 * that is built and tested but ships behind a default-off flag, can be shown
 * here WITH its precondition named, instead of being quietly padded in among
 * the unconditional ones or dropped entirely.
 *
 * HONESTY CONTRACT — every sentence must survive a senior engineer opening the
 * cited file, so:
 *
 *  • LEVEL I is unconditional: on by default, no flag, no dialect, no
 *    operational precondition. The five numbered callouts on the plate are all
 *    Level I; they are the five strongest, not a different category.
 *  • LEVEL II and LEVEL III entries MUST each carry a `gate` — the deployment
 *    precondition or the flag name — rendered as part of the entry, never as a
 *    footnote. A tier entry without its gate is a lie by omission, and
 *    specimen-sheet.test.tsx fails the build if one is missing.
 *  • Nothing here claims redaction on the agent path. There is none:
 *    `server/src/mcp/` never imports `services/pii.py`. The gap is NOT_CLAIMED,
 *    stated as absent — not Level II awaiting configuration, not Level III
 *    awaiting a flag.
 *  • Citations are file path + symbol/test NAME. Never line numbers: they rot
 *    on the next edit, and a stale citation is worse than none.
 *
 * EVERY NUMBER BELOW WAS MEASURED, not quoted. `scripts` in the report:
 *  15 mintable scope strings → 9 effective, 3 dropped (normalize_scopes, run);
 *  60s capability TTL, 90d key TTL, 20/min, 60/min (settings, read);
 *  366 / 200 / 500 / 2000 / 256 / 4096 (module constants, read);
 *  13 tools, 2 DB doors, 6 propose kinds, 37 tenant tables (counted in source);
 *  14 resource→scope entries, 1 of them deliberately None (_RESOURCE_SCOPES).
 *  NOTE: an earlier audit put the tenant-table count at 35 and the in-file
 *  comment still says "29 + 6". Both are stale — TENANT_TABLES holds 37 unique
 *  names today. 37 is what ships here.
 */

/* ── Citations ───────────────────────────────────────────────────────────── */

export type Citation = {
  /** Repo-relative path. Rendered muted — the symbol is the part you look for. */
  path: string;
  /** Function, class, test or module-constant NAME. Never a line number. */
  symbol?: string;
  kind: "source" | "test" | "migration";
};

/* ── The plates: the strongest Level I mechanisms, called out ────────────── */

/** A callout number. Ordered by the argument, not by position on the plate:
 *  ② names the two doors, ③ is the lock those doors now carry. */
export type PlateN = 1 | 2 | 3 | 4 | 5;

export type Plate = {
  n: PlateN;
  /** The banknote feature this control is the software analogue of. */
  feature: string;
  /** What the mechanism is, in one line. */
  mechanism: string;
  /** Where the enforcement lives — the reason it ranks where it does. */
  kind: string;
  threat: string;
  enforcement: string;
  proof: Citation[];
  /** The detail that turns "we claim it" into "we proved it". */
  tell: string;
  /** Where on the note the feature sits, in plate viewBox units. */
  anchor: [number, number];
  /** Where its numbered callout sits, in the sheet margin. */
  marker: [number, number];
};

export const PLATES: Plate[] = [
  {
    n: 1,
    feature: "The security thread",
    mechanism: "A separate signing key per token family",
    kind: "A cryptographic boundary",
    threat:
      "One secret signs every kind of token and a claim tells them apart. Forget that check in one place — a route added next quarter, a helper reused in a hurry — and a sign-in token is accepted as an agent capability.",
    enforcement:
      "Each of the three families signs with its own 32-byte key, derived from the master secret by HKDF-SHA256 under the label budget-ai/jwt/session, /assistant_action or /mcp. A session token presented as an agent capability does not fail a claim check. It fails signature verification, before any claim is read. The required audience and issuer, and the type check above them, are backstops rather than the boundary.",
    proof: [
      { path: "server/src/services/token_keys.py", symbol: "signing_key()", kind: "source" },
      { path: "server/src/mcp/policy.py", symbol: "verify_capability()", kind: "source" },
      {
        path: "server/tests/test_mcp_policy.py",
        symbol: "test_auth_access_token_rejected_as_capability",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_policy.py",
        symbol: "test_wrong_typ_with_correct_audience_still_rejected",
        kind: "test",
      },
    ],
    tell:
      "The last test mints a token with the correct MCP key and the correct audience — the outer layer deliberately satisfied — and asserts the type check still refuses it.",
    anchor: [330, 118],
    marker: [330, 26],
  },
  {
    n: 2,
    feature: "The two doorways",
    mechanism: "Database access is a closed set of exactly two modules",
    kind: "A guard that runs in the build",
    threat:
      "Architectural boundaries erode by contribution, not by attack. A rule that says only one place may open a database session holds for exactly as long as everyone remembers it.",
    enforcement:
      "A test parses the syntax tree of every module under the MCP package and asserts that the set importing a database session is exactly two files: vault.py, which reads, and actions.py, which drafts. Equality, not a blocklist — a new module reaching for a session fails the build, and a sanctioned door that stops being one is reported as dead. The rule visibly shaped the code: the audit writer lives outside the package precisely so the boundary holds, and its module docstring says so.",
    proof: [
      {
        path: "server/tests/test_mcp_import_guard.py",
        symbol: "test_db_doors_are_exactly_the_sanctioned_set",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_import_guard.py",
        symbol: "test_guard_bites_on_planted_violation",
        kind: "test",
      },
      { path: "server/src/services/mcp_audit_store.py", symbol: "persist()", kind: "source" },
    ],
    tell:
      "The second test synthesises a violating module and asserts the scanner catches it — so the guard can never pass quietly because it stopped looking.",
    anchor: [400, 276],
    marker: [340, 444],
  },
  {
    n: 3,
    feature: "The ward on each door",
    mechanism: "A capability is checked against the resource it is spent on",
    kind: "A gate beneath the layer that mints it",
    threat:
      "The vault's docstring advertised a scope check read() never performed: it handed the token's scopes to the dispatcher, which consulted them for one resource only — the composed context. Every other one opened on a capability minted for any other. Nothing outside could reach it — policy.require runs before minting, and minting refuses a scope the principal lacks — but it was the one place here where enforcement sat above the layer at which the mistake would be made.",
    enforcement:
      "read() maps the resource to its required scope and refuses before it opens a database session. The map is fail-closed: an absent resource is denied, so adding one without a scope decision breaks the request instead of quietly exposing the data. Fourteen resources are mapped, thirteen to a scope; ping deliberately to none, because it echoes back only the user id the verified token already establishes. Both refusals are audited — deny:missing_scope, deny:unknown_resource — before the error is raised. The docstring is now true.",
    proof: [
      { path: "server/src/mcp/vault.py", symbol: "_RESOURCE_SCOPES", kind: "source" },
      { path: "server/src/mcp/vault.py", symbol: "read()", kind: "source" },
      {
        path: "server/tests/test_mcp_vault_scope_binding.py",
        symbol: "test_accounts_capability_cannot_read_transactions",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_vault_scope_binding.py",
        symbol: "test_transactions_capability_cannot_read_net_worth",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_vault_scope_binding.py",
        symbol: "test_budgets_capability_cannot_run_what_if",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_vault_scope_binding.py",
        symbol: "test_missing_scope_denial_is_audited",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_vault_scope_binding.py",
        symbol: "test_every_dispatchable_resource_has_a_scope_decision",
        kind: "test",
      },
    ],
    tell:
      "The last test parses the resources out of the dispatcher's own source and asserts every one appears in the map, so the guard cannot rot as new ones are added. Neutering the check turns exactly four of the eight red — the three cross-resource denials and the audit assertion; the unknown-resource case stays green, because the dispatcher refuses that one again on its own.",
    // The leader threads the gap between the refused door and the locked one.
    // Measured, not guessed: at 620 the line grazed the last glyph of "a third
    // door fails the build" (which ends at x≈539); 640 clears it by 7 units.
    anchor: [468, 320],
    marker: [640, 444],
  },
  {
    n: 4,
    feature: "The serial register",
    mechanism: "The agent-access log is append-only in the database",
    kind: "A trigger below the application",
    threat:
      "The model's docstring called this table append-only long before anything made it so. A convention written in a comment does not stop a recorded denial being rewritten into an allow.",
    enforcement:
      "BEFORE UPDATE and BEFORE DELETE triggers on the table itself — RAISE(ABORT) on SQLite, a PL/pgSQL RAISE EXCEPTION on Postgres — installed both from the model when the schema is created and from an Alembic migration, so a created database and a migrated one carry the identical guard. The cost is written down beside it: a user row can no longer cascade-delete while its audit rows exist.",
    proof: [
      { path: "server/src/db/models.py", symbol: "mcp_audit_log_append_only()", kind: "source" },
      {
        path: "server/migrations/versions/b8f720260720_mcp_audit_log_append_only.py",
        kind: "migration",
      },
      {
        path: "server/tests/test_mcp_audit_append_only.py",
        symbol: "test_rewriting_a_denial_into_an_allow_is_blocked",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_audit_append_only.py",
        symbol: "test_appending_still_works",
        kind: "test",
      },
    ],
    tell:
      "The tests pin the specific threat — laundering a denial into an allow — and then prove the guard did not disable appending along with it. They pass on both dialects.",
    anchor: [872, 136],
    marker: [956, 66],
  },
  {
    n: 5,
    feature: "The blank the press left",
    mechanism: "A silent failure, found and made loud",
    kind: "A failure mode, hardened",
    threat:
      "The audit writer opened its own database session without binding the tenant. In a deployment that had switched Postgres row-level security on, the policy compared the row against an unset setting and rejected every insert — and a bare except swallowed it. The installations that hardened themselves were the ones that lost their agent-access ledger, with no signal that anything had happened.",
    enforcement:
      "The tenant is bound before the insert, and the silent swallow is now a logged discard carrying its stack trace. Auditing still never breaks a read — that part was right — but it can no longer empty itself without saying so. The reasoning sits in the code: an audit trail that can vanish quietly is worse than one that fails loudly.",
    proof: [
      { path: "server/src/services/mcp_audit_store.py", symbol: "persist()", kind: "source" },
      {
        path: "server/tests/test_mcp_audit_rls_postgres.py",
        symbol: "test_audit_row_persists_under_rls",
        kind: "test",
      },
    ],
    tell:
      "The regression test creates a real NOSUPERUSER role, SET ROLEs onto it, then counts the rows back with RESET ROLE — so it measures what was written, not what the policy lets the writer read back.",
    anchor: [860, 300],
    marker: [956, 350],
  },
];

/* ── The three verification levels ───────────────────────────────────────── */

export type TierEntry = {
  title: string;
  body: string;
  /**
   * Level II / Level III ONLY, and mandatory there: the deployment precondition
   * or the flag name, rendered inside the entry. Level I entries have none by
   * definition — that is what Level I means.
   */
  gate?: string;
  proof: Citation[];
};

export type Tier = {
  id: "i" | "ii" | "iii";
  numeral: "I" | "II" | "III";
  /** The name of the level, in the house voice. */
  name: string;
  /** How a note of this level is checked — the currency metaphor, literally. */
  lens: string;
  /** What qualifies a mechanism for this level. */
  rule: string;
  entries: TierEntry[];
};

const TIER_I_ENTRIES: TierEntry[] = [
  {
    title: "The read session never commits, and the user id never comes from the agent",
    body: "The vault opens its own session, dispatches, and unconditionally rolls back and closes in a finally — there is no commit anywhere in the file. No tool accepts a user id: it travels credential → principal → capability claim → dispatch, and the propose handler swallows any extra keyword an agent tries to inject. The test decodes the minted capability and asserts the id came from there and nowhere else.",
    proof: [
      { path: "server/src/mcp/vault.py", symbol: "read()", kind: "source" },
      {
        path: "server/tests/test_mcp_vault.py",
        symbol: "test_rollback_called_on_exception",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_server.py",
        symbol: "test_user_id_comes_from_principal_not_args",
        kind: "test",
      },
    ],
  },
  {
    title: "The stored key is a hash and a twelve-character stub",
    body: "A key is bdgt_live_ plus 32 bytes of CSPRNG output; only its SHA-256 digest and a 12-character display prefix are kept, and the raw string is returned exactly once. Plain SHA-256 is right here precisely because the pre-image is 256 bits — a password KDF would buy nothing but latency. Keys expire after 90 days by default and revocation is owner-scoped and idempotent; because the transport is stateless the principal is re-resolved on every request, so a revoked key or a disabled owner is locked out on the next call rather than at session expiry. The key-management endpoints depend on a browser session, never on an MCP key: a key has no authority over its own lifecycle.",
    proof: [
      { path: "server/src/services/mcp_key_service.py", symbol: "_hash_key()", kind: "source" },
      {
        path: "server/tests/test_mcp_keys.py",
        symbol: "test_expired_key_resolves_to_none",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_hardening.py",
        symbol: "test_stateless_http_enabled",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_keys_api.py",
        symbol: "test_unauthenticated_returns_401",
        kind: "test",
      },
    ],
  },
  {
    title: "A rejection says nothing, and a credential never travels in a URL",
    body: "Credentials are read from headers only. A token placed in the query string is never consulted — the request still fails, and only the message changes, so a misplaced token is not mistaken for no credentials at all. Unknown hash, revoked, expired and owner-disabled all fold into one None and one fixed body: there is no oracle telling a prober that a guessed key exists but has expired.",
    proof: [
      { path: "server/src/mcp/server.py", symbol: "_has_query_token()", kind: "source" },
      { path: "server/src/services/mcp_key_service.py", symbol: "resolve()", kind: "source" },
      {
        path: "server/tests/test_mcp_server.py",
        symbol: "test_token_in_query_string_rejected",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_hardening.py",
        symbol: "test_disabled_deny_message_stays_opaque",
        kind: "test",
      },
    ],
  },
  {
    title: "A capability lives sixty seconds and can only narrow",
    body: "Every tool call mints a fresh token carrying the user id, the key id, a random jti and a 60-second expiry — and minting refuses any scope the key does not already hold, and refuses an empty scope list. Upstream, 15 mintable scope strings normalise to 9 effective read scopes: three legacy read names map onto modern ones, and transactions:write, budgets:write and assistant:chat are dropped to nothing rather than translated — at mint, and again on every resolve, so an old key cannot carry a stale write scope into a future where a write tool exists.",
    proof: [
      { path: "server/src/mcp/policy.py", symbol: "issue_capability()", kind: "source" },
      { path: "server/src/mcp/scopes.py", symbol: "normalize_scopes()", kind: "source" },
      { path: "server/tests/test_mcp_policy.py", symbol: "test_escalation_blocked", kind: "test" },
      {
        path: "server/tests/test_mcp_keys.py",
        symbol: "test_create_mixed_scopes_keeps_only_usable",
        kind: "test",
      },
    ],
  },
  {
    title: "A section you didn't grant says so out loud",
    body: "The composed context resource mints a capability for the intersection of your scopes and the section's, so one coarse grant cannot aggregate income, balances, budgets and goals into a single payload. An unauthorised section comes back as an explicit “unavailable, requires read:…” stub rather than silently missing — the model is told what it could not see, instead of guessing.",
    proof: [
      { path: "server/src/mcp/context.py", symbol: "ContextBuilder.build()", kind: "source" },
      {
        path: "server/tests/test_mcp_context.py",
        symbol: "test_each_section_gated_by_its_scope",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_read_context_alone_exposes_nothing_extra",
        kind: "test",
      },
    ],
  },
  {
    title: "Cross-user isolation, hammered rather than asserted",
    body: "Eight threads, twenty-five iterations each, alternating two users' capability tokens against a file-backed engine — the production connection shape, not the in-memory shortcut that would hide the bug being hunted. A companion test pins the subtler half: the identity travels in a ContextVar, and the framework runs synchronous tools in a worker thread, so the principal has to survive a hop that pooled threads make dangerous.",
    proof: [
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_concurrent_cross_user_vault_reads_never_mix",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_principal_contextvar_propagates_into_worker_thread",
        kind: "test",
      },
    ],
  },
  {
    title: "Agent-supplied input is bounded, typed, and never a 500",
    body: "A forecast horizon is clamped to 366 days. A what-if overlay is counted across its five list keys before deserialisation and refused above 200 items. A transaction limit is clamped to 500. limit and offset must be true integers, with bool excluded explicitly — in Python a bool is an int, and that is a type-confusion waiting to happen. Every unexpected exception is caught and re-raised as a flat “Data layer error.”, so no driver message or stack trace reaches the caller.",
    proof: [
      { path: "server/src/mcp/vault.py", symbol: "_dispatch()", kind: "source" },
      { path: "server/src/services/read_queries.py", symbol: "_clamp_limit()", kind: "source" },
      {
        path: "server/tests/test_mcp_hardening_review.py",
        symbol: "test_oversized_overlay_rejected",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_vault.py",
        symbol: "test_original_exception_not_leaked",
        kind: "test",
      },
    ],
  },
  {
    title: "The injection test is written to be able to fail",
    body: "Every read goes through the ORM with bound parameters; nothing on the agent path builds SQL by string. The test that proves it passes “Food'); DROP TABLE expenses;--” as a category and then asserts the expenses table and its rows still exist afterwards — an assertion that would actually catch the failure, rather than merely observing that the query returned nothing.",
    proof: [
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_sql_injection_in_category_is_parameterized",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_out_of_range_account_id_denied_not_crashed",
        kind: "test",
      },
    ],
  },
  {
    title: "Text the model writes is screened before it is stored",
    body: "When the in-app assistant drafts a proposal, the one free-text field that lands in your ledger is matched against a deterministic screen on an NFKC-normalised copy, so homoglyph and zero-width evasions do not slip past the patterns — while the original text is what gets displayed. A blocked rationale is replaced with a neutral factual line rather than failing the feature.",
    proof: [
      { path: "server/src/services/game/firewall.py", symbol: "screen_output()", kind: "source" },
      {
        path: "server/tests/test_assisted_action.py",
        symbol: "test_propose_screens_advice_rationale",
        kind: "test",
      },
    ],
  },
  {
    title: "The tenant-table list is derived from the schema, not kept by hand",
    body: "A dialect-agnostic test asserts that the set of tables carrying a tenant policy equals exactly every model with a user_id column, minus two deliberately excluded credential tables — 37 tables today. A new model with a user_id that nobody adds to the list fails the build instead of shipping unpoliced. The exclusions are pinned by their own test: refresh_tokens and mcp_keys are looked up by an unguessable hash before any tenant context exists, so a fail-closed policy there would brick login and agent auth alike. This guard runs in every build. The policies it guards are Level II.",
    proof: [
      { path: "server/src/db/rls.py", symbol: "TENANT_TABLES", kind: "source" },
      {
        path: "server/tests/test_rls_tenant_tables.py",
        symbol: "test_tenant_tables_matches_user_id_columns_exactly",
        kind: "test",
      },
      {
        path: "server/tests/test_rls_tenant_tables.py",
        symbol: "test_excluded_credential_tables_are_real_but_unpoliced",
        kind: "test",
      },
    ],
  },
];

const TIER_II_ENTRIES: TierEntry[] = [
  {
    title: "Tenant isolation enforced by the database itself",
    gate:
      "Needs Postgres, ENABLE_RLS=true — the setting default and .env.example both ship false — and an application role that is not a superuser, because a superuser bypasses row-level security even under FORCE and no code can prevent that. The two tests below are skipped entirely unless the suite runs against Postgres.",
    body: "Both sanctioned doors bind app.user_id for the transaction through set_config(…, true), so the binding cannot leak across a pooled connection. The policy reads it back through NULLIF(current_setting('app.user_id', true), '') — load-bearing, because a custom setting reverts to an empty string rather than to unset when a transaction ends, and a bare cast would raise instead of failing closed. Unset or emptied yields NULL, and user_id = NULL matches no rows. One tenant-isolation policy is installed per tenant table, 37 today, from the same list the build guard checks.",
    proof: [
      { path: "server/src/db/rls.py", symbol: "set_tenant()", kind: "source" },
      { path: "server/migrations/versions/d1f4a6c8b3e5_enable_rls.py", kind: "migration" },
      {
        path: "server/tests/test_rls_enforcement_postgres.py",
        symbol: "test_missing_context_fails_closed",
        kind: "test",
      },
      {
        path: "server/tests/test_rls_postgres.py",
        symbol: "test_set_local_is_transaction_scoped",
        kind: "test",
      },
    ],
  },
  {
    title: "Twenty requests a minute, per key",
    gate:
      "On by default, but the window lives in memory in a single process. A second uvicorn worker multiplies every limit and a restart clears every window — the app logs exactly that as a startup warning rather than leaving you to find out.",
    body: "Once the principal resolves, a moving-window limiter keyed on the key id throttles the request, records the refusal as rate_limited, and answers 429 with Retry-After: 60. The setting is read fresh on each request rather than captured at construction, so turning the limiter off in configuration takes effect without a restart.",
    proof: [
      { path: "server/src/mcp/server.py", symbol: "MCPAuthMiddleware", kind: "source" },
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_per_key_rate_limit_trips_with_429",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_failure_modes.py",
        symbol: "test_rate_limit_is_per_key_not_global",
        kind: "test",
      },
    ],
  },
  {
    title: "Sixty a minute per address, shed before the database is touched",
    gate:
      "The same single-process precondition as above. And TRUST_PROXY ships false, so X-Forwarded-For is ignored and every client behind one NAT shares a bucket — the right trade for security, a coarse one for availability.",
    body: "The pre-auth throttle runs at the very top of the middleware, ahead of any credential lookup, so a flood of invalid keys is shed without costing a query. The proving test does not check the status code alone: it asserts the database factory was never invoked at all.",
    proof: [
      { path: "server/src/mcp/server.py", symbol: "_client_key_from_scope()", kind: "source" },
      {
        path: "server/tests/test_mcp_hardening.py",
        symbol: "test_preauth_throttle_skips_db",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_hardening.py",
        symbol: "test_preauth_throttle_is_per_client",
        kind: "test",
      },
    ],
  },
];

const TIER_III_ENTRIES: TierEntry[] = [
  {
    title: "The agent surface itself is off by default",
    gate: "MCP_ENABLED=false — the setting default, and what .env.example ships.",
    body: "The MCP application is only constructed and mounted when the flag is on. With it off the app is never built, /mcp is never mounted, and every /mcp path falls through to the single-page-app catch-all as a 404. There is nothing listening to authenticate against, which is a different and stronger thing than an endpoint that refuses you.",
    proof: [
      { path: "server/src/mcp/server.py", symbol: "build_mcp_starlette()", kind: "source" },
      {
        path: "server/tests/test_mcp_server.py",
        symbol: "test_mcp_enabled_is_false_by_default",
        kind: "test",
      },
    ],
  },
  {
    title: "The one write door has two independent gates",
    gate: "mcp_propose_enabled defaults to False.",
    body: "Gate one: propose:actions is deliberately absent from the mintable scope list and is added to the effective allow-set only when the flag is on — so a default deployment cannot even mint a propose-capable key, let alone use one. Gate two: the propose handler refuses at step zero regardless of what scope a key carries, and records the refusal as propose_disabled. Two gates that do not share a mechanism, so one of them failing open is not enough.",
    proof: [
      { path: "server/src/services/mcp_key_service.py", symbol: "create()", kind: "source" },
      { path: "server/src/mcp/actions.py", symbol: "propose()", kind: "source" },
      {
        path: "server/tests/test_mcp_hardening_review.py",
        symbol: "test_not_mintable_when_disabled",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_actions.py",
        symbol: "test_ships_dark_when_flag_off",
        kind: "test",
      },
    ],
  },
  {
    title: "Even switched on, it drafts and cannot execute",
    gate:
      "Everything here sits behind mcp_propose_enabled. Origination is behind a second, separate flag — rail_origination_enabled, also False — and points only at a sandbox host.",
    body: "kind is checked against a six-value allowlist, status is forced to proposed with settlement left empty, and the row is deduplicated by reference. Before any write: rationale must be a string of at most 2,000 characters, the two references at most 256 each, how a JSON-serialisable dict encoding to at most 4,096 bytes, and amount a non-bool number greater than zero. No tool named execute exists on the surface — a test enumerates the live tool inventory and asserts it.",
    proof: [
      { path: "server/src/mcp/actions.py", symbol: "_validate_fields()", kind: "source" },
      { path: "server/src/services/assisted_action_service.py", symbol: "propose()", kind: "source" },
      {
        path: "server/tests/test_assisted_action.py",
        symbol: "test_execute_absent_from_mcp_and_assistant_surface",
        kind: "test",
      },
      {
        path: "server/tests/test_mcp_hardening_review.py",
        symbol: "test_oversized_how_rejected",
        kind: "test",
      },
    ],
  },
];

export const TIERS: Tier[] = [
  {
    id: "i",
    numeral: "I",
    name: "In plain sight",
    lens: "checked with the naked eye",
    rule: "On in every deployment. No flag, no dialect, no operational precondition — if the code runs, these run. The five numbered callouts above are Level I too; they are the strongest of these, not a different kind.",
    entries: TIER_I_ENTRIES,
  },
  {
    id: "ii",
    numeral: "II",
    name: "Under the lamp",
    lens: "checked under raking light",
    rule: "Real, enforced and tested — and conditional. Each one names what a deployment has to do before it protects anything, in the entry, not in a footnote.",
    entries: TIER_II_ENTRIES,
  },
  {
    id: "iii",
    numeral: "III",
    name: "Under the microscope",
    lens: "checked in the laboratory",
    rule: "Built, tested, and shipped switched off. Named here with the flag that holds them, because a control you cannot reach is not a control you have — and because the flag is the honest part.",
    entries: TIER_III_ENTRIES,
  },
];

/* ── The engraved figure block ───────────────────────────────────────────── */

export type Figure = { value: string; caption: string };

/**
 * Measured, not estimated, and never rounded.
 *
 * The two test counts were OBSERVED by running the backend suite on the default
 * SQLite configuration (`1573 passed, 17 skipped`), and again with
 * TEST_DATABASE_URL pointed at PostgreSQL 17.7, where the 17 Postgres-only
 * tests stop being skipped (`1590 passed`, no skips in the summary line). Both
 * are reported exactly as pytest printed them. The two runs are tied together:
 * every one of the 17 SQLite skips reports the same reason — "RLS is
 * Postgres-only" — so the second figure is the first plus exactly those.
 *
 * The 4 overstated claims are each a diff, not an impression. TWO were closed by
 * building what the docstring already claimed:
 *   • the audit-log model called its table append-only with nothing behind it —
 *     now BEFORE UPDATE/DELETE triggers on both dialects;
 *   • the vault's docstring listed a scope check that `read()` never performed —
 *     now `_RESOURCE_SCOPES`, checked before the session opens.
 * TWO were closed by narrowing the wording, because the code was right and the
 * sentence was not:
 *   • the landing's "inspect every request" → "every request your key makes",
 *     because anonymous denials are never persisted;
 *   • the Vault's PII claim, fenced to the in-app assistant, because the agent
 *     path does not use that filter at all.
 *
 * The "42 audited" is a record of the audit pass and is deliberately NOT bumped
 * for the scope gate: that mechanism did not exist to be audited — the audit is
 * what produced it.
 */
export const IMPACT: Figure[] = [
  { value: "42", caption: "security mechanisms audited across the agent surface" },
  {
    value: "4",
    caption:
      "overstated claims found and corrected — two by building the enforcement the docstring described, two by narrowing the wording",
  },
  {
    value: "1",
    caption:
      "silent-failure bug found and fixed: enabling row-level security discarded every audit row, swallowed by a bare except",
  },
  {
    value: "1,573 / 1,590",
    caption: "backend tests passing on SQLite, and on Postgres 17.7 with none skipped",
  },
];

/**
 * What a specimen sheet leaves off is information too — and the tier system
 * must not be allowed to absorb it. This one is not Level II awaiting a
 * deployment, nor Level III awaiting a flag. It is absent.
 */
export const NOT_CLAIMED = {
  head: "Not on this sheet, at any level",
  body: "The agent path performs no redaction. Transaction titles, merchant names and imported memos reach the model you connect, verbatim. There is no flag that turns this on and no deployment that configures it — the scrubber this product owns runs on the in-app assistant and is never imported by the agent package.",
  proof: [
    {
      path: "server/tests/test_mcp_failure_modes.py",
      symbol: "test_freetext_transaction_title_passes_through_verbatim",
      kind: "test",
    },
  ] as Citation[],
  tell: "A passing test asserts the payload survives, rather than hiding that it does.",
};

/* ── Plate geometry ──────────────────────────────────────────────────────── */

/** The engraved sheet's coordinate space. Callout markers live in the margins. */
export const VIEW = { w: 1000, h: 470 } as const;

/** The note field itself, inset inside the sheet. */
export const NOTE = { x: 110, y: 60, w: 790, h: 350 } as const;

/** A marker's position as a CSS percentage of the plate box. */
export function markerStyle(marker: [number, number]) {
  return {
    "--spx-x": `${(marker[0] / VIEW.w) * 100}%`,
    "--spx-y": `${(marker[1] / VIEW.h) * 100}%`,
  } as CSSProperties;
}
