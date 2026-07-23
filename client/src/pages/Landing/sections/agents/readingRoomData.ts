/**
 * The Reading Room's example ledger.
 *
 * Every scope id, station, and mechanism below is the real one — the scope
 * strings match server/src/settings.py (mcp_allowed_scopes), the stations match
 * the actual request path (key → policy gate → capability → vault → audit), and
 * the denial text matches what the policy gate really returns. Only the ledger
 * figures are illustrative, and they're consistent with the rest of the landing
 * (the hero's $1,210.18 safe-to-spend).
 */

/* ── Scopes ──────────────────────────────────────────────────────────────── */

export type ScopeId =
  | "read:accounts"
  | "read:transactions"
  | "read:budgets"
  | "read:goals"
  | "read:forecast"
  | "read:networth"
  | "read:subscriptions"
  | "read:scenarios"
  | "read:context";

export type Scope = {
  id: ScopeId;
  /** What a person calls it. */
  label: string;
  /** What it actually opens, in one clause. */
  clause: string;
};

export const SCOPES: Scope[] = [
  { id: "read:accounts", label: "Accounts", clause: "names & balances" },
  { id: "read:transactions", label: "Transactions", clause: "every posted debit and credit" },
  { id: "read:budgets", label: "Budgets", clause: "envelopes, limits & pace" },
  { id: "read:goals", label: "Goals", clause: "targets & progress" },
  { id: "read:forecast", label: "Forecast", clause: "the cash outlook ahead" },
  { id: "read:networth", label: "Net worth", clause: "totals & trend" },
  { id: "read:subscriptions", label: "Subscriptions", clause: "detected recurring charges" },
  { id: "read:scenarios", label: "Scenarios", clause: "what-if projections" },
  { id: "read:context", label: "Context", clause: "a composed snapshot" },
];

/** What a fresh visitor arrives holding — enough to answer, not everything. */
export const DEFAULT_GRANTED: ScopeId[] = [
  "read:accounts",
  "read:transactions",
  "read:forecast",
  "read:scenarios",
  "read:subscriptions",
  "read:context",
];

/* ── The three requests ──────────────────────────────────────────────────── */

/** A line of the answer. `figure` money is set in the sober ledger inks. */
export type DocketLine = {
  label: string;
  value: string;
  /** Money direction, for the colour law. Omit for neutral figures. */
  ink?: "credit" | "debit";
};

export type Request = {
  id: string;
  /** The question, as a visitor would type it. */
  question: string;
  /** Shorthand for the slip's header. */
  filed: string;
  /** Scopes the request genuinely needs — the gate checks exactly these. */
  needs: ScopeId[];
  /** The MCP tools it would call, in order (real tool names). */
  tools: string[];
  /** The answer, when every needed scope is granted. */
  verdict: string;
  lines: DocketLine[];
  /** The reasoning line under the figures — how it got there. */
  basis: string;
  /** Latency the audit row reports (illustrative but plausible). */
  latencyMs: number;
  /** The audit row's resource label. */
  resource: string;
  /** Truncated params fingerprint, as the real audit log stores it. */
  paramsHash: string;
};

export const REQUESTS: Request[] = [
  {
    id: "flight",
    question: "Can I buy a $600 flight and still cover rent?",
    filed: "A purchase, tested against the month",
    needs: ["read:accounts", "read:forecast", "read:scenarios"],
    tools: ["get_accounts", "get_forecast", "run_what_if"],
    verdict: "Yes — with $610.18 of room left.",
    lines: [
      { label: "Safe to spend today", value: "$1,210.18" },
      { label: "The flight", value: "−$600.00", ink: "debit" },
      { label: "Left until payday", value: "$610.18", ink: "credit" },
      { label: "Rent, due the 1st", value: "covered" },
    ],
    basis:
      "Rent of $1,450 is already reserved against the 1st, and no bill between now and payday exceeds the remainder. The low point of the month moves from $792 to $192 on the 27th.",
    latencyMs: 96,
    resource: "run_what_if",
    paramsHash: "a3f0c7d1",
  },
  {
    id: "creep",
    question: "Which subscriptions quietly became more expensive?",
    filed: "Recurring charges, checked for drift",
    needs: ["read:subscriptions"],
    tools: ["get_subscriptions"],
    verdict: "Two raised their price without an email.",
    lines: [
      { label: "StreamMax · monthly", value: "$11.99 → $15.49", ink: "debit" },
      { label: "Northwind Storage · monthly", value: "$6.00 → $9.99", ink: "debit" },
      { label: "Extra per year", value: "−$89.88", ink: "debit" },
      { label: "Everything else", value: "unchanged" },
    ],
    basis:
      "Both merchants were matched across statements by cadence and amount, so a rename or a new descriptor doesn't hide the increase. Two more subscriptions have gone unused for 60 days.",
    latencyMs: 71,
    resource: "get_subscriptions",
    paramsHash: "5b19e402",
  },
  {
    id: "outlook",
    question: "What changed in my 30-day cash outlook?",
    filed: "The month ahead, since last week",
    needs: ["read:forecast", "read:context"],
    tools: ["get_forecast", "budget://context"],
    verdict: "Tighter by $180 — one annual bill landed in the window.",
    lines: [
      { label: "Low point", value: "$412.00" },
      { label: "When", value: "the 14th" },
      { label: "Change since last week", value: "−$180.00", ink: "debit" },
      { label: "Modeled paths below zero", value: "fewer than 12 of 240" },
    ],
    basis:
      "Annual insurance of $180 now posts on the 12th, two days before the trough. Income timing is unchanged, and the forecast still clears every scheduled bill.",
    latencyMs: 118,
    resource: "get_forecast",
    paramsHash: "c740b8ae",
  },
];

/* ── The stations a request passes through ───────────────────────────────── */

export type Station = {
  id: string;
  /** The plate on the aperture. */
  name: string;
  /** What a visitor understands is happening here. */
  plain: string;
  /** The stamp pressed when the request clears it. */
  stamp: string;
  /** The mechanism, for the engineer view — what the code actually does. */
  mechanism: string;
  /** The evidence: the file or test that proves it. */
  evidence: string;
};

export const STATIONS: Station[] = [
  {
    id: "slip",
    name: "The Request",
    plain: "Your assistant asks a question on your behalf.",
    stamp: "Received",
    mechanism:
      "The agent presents an opaque key. Only its SHA-256 hash was ever stored, so the key on file cannot be read back or reissued — a lost key is re-minted, never recovered.",
    evidence: "mcp_key_service.resolve() · the raw key is shown exactly once",
  },
  {
    id: "scopes",
    name: "The Clauses",
    plain: "Only the permissions you granted travel with it.",
    stamp: "Scoped",
    mechanism:
      "The key resolves to an immutable Principal — user id, key id, and the granted scope set. Legacy scope names are normalised here, and write-ish ones are dropped rather than translated.",
    evidence: "principal.py · a frozen dataclass, not a mutable session",
  },
  {
    id: "gate",
    name: "The Policy Gate",
    plain: "The request is checked against what you allowed.",
    stamp: "Narrowed",
    mechanism:
      "The gate mints a capability for the single scope this call needs, and refuses any scope the key doesn't already hold. A capability can narrow, never widen — it lives 60 seconds and is bound to aud=\"mcp\", so a session or action token can't be passed off as one.",
    evidence: "policy.issue_capability() · test_escalation_blocked",
  },
  {
    id: "vault",
    name: "The Vault",
    plain: "Your data is read — and only read.",
    stamp: "Read-only",
    mechanism:
      "One module is allowed to open a database session, and it opens a read-only one that always rolls back. The user id comes from the verified capability, never from anything the agent sent.",
    evidence: "vault.read() · test_db_doors_are_exactly_the_sanctioned_set",
  },
  {
    id: "docket",
    name: "The Answer",
    plain: "The answer comes back composed, with its reasoning.",
    stamp: "Filed",
    mechanism:
      "Sections you didn't grant come back as explicit \"unavailable, requires read:x\" stubs rather than silently missing — the assistant is told what it couldn't see.",
    evidence: "context.ContextBuilder.build() · required_scope stubs",
  },
  {
    id: "receipt",
    name: "The Receipt",
    plain: "Authorized and scope-denied calls are recorded for review.",
    stamp: "Entered",
    mechanism:
      "Each call writes a row: resource, allow or deny, latency, and a truncated hash of the parameters. Inputs are fingerprinted, never stored raw, and the ledger is scoped to its owner.",
    evidence: "mcp_audit_log · test_audit_owner_scoped",
  },
];

/** The station a denied request stops at. */
export const GATE_INDEX = STATIONS.findIndex((s) => s.id === "gate");

/**
 * The one honest sentence about writing. The propose door exists, ships off, and
 * never moves money on its own — said plainly so the section can't be read as
 * "an agent with your bank account".
 */
export const WRITE_TRUTH = {
  headline: "The only write is a proposal.",
  body: "With the propose door switched on, an assistant can draft an action — a transfer, a payment, a goal contribution — and it lands in your ledger marked “proposed”. Executing it is a tap you make, in the app. Nothing else the agent can reach is writable, and the door is off unless you turn it on.",
} as const;
