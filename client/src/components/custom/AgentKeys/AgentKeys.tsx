import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api from "@/lib/api";
import { cn } from "@/lib/utils";
import { useStore } from "@/store/store";
import { useToast } from "@/hooks/useToast";
import { Seal } from "@/components/engraving/Seal";
import { Stamp } from "@/components/engraving/Stamp";
import { GuillocheBand, CornerRosette } from "@/components/engraving/Guilloche";
import { CapabilityStamps } from "./CapabilityStamps";
import { AuditLedger } from "./AuditLedger";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";

/* ──────────────────────────────────────────────────────────────────────────
 * THE BUREAU OF SEALED AUTHORIZATIONS
 *
 * An MCP capability key is a *Letter of Marque*: a sealed, scoped bearer
 * instrument that lets a named agent (Claude, say) READ the ledger and nothing
 * more. This panel issues, registers, and revokes them in the Engraver's Ledger
 * language — wax seals, status stamps, a guilloché security strip on the
 * one-time secret, scope clauses set in stamped smallcaps.
 * ────────────────────────────────────────────────────────────────────────── */

interface KeyMeta {
  id: number;
  name: string;
  key_prefix: string;
  scopes: string;
  created_at: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  revoked: boolean;
}

interface MintedKey {
  raw_key: string;
  id: number;
  name: string;
  key_prefix: string;
  scopes: string;
  expires_at: string | null;
}

/** The grantable read scopes, in the order they read on a writ. Every scope the
 *  MCP surface accepts is grantable here (server/src/settings.py mcp_allowed_scopes);
 *  the propose door is deliberately absent — it ships dark and is never a picker. */
const SCOPES: { id: string; label: string; clause: string }[] = [
  { id: "read:accounts", label: "Accounts", clause: "names & balances of your accounts" },
  { id: "read:transactions", label: "Transactions", clause: "every posted debit and credit" },
  { id: "read:budgets", label: "Budgets", clause: "envelopes, limits & pace" },
  { id: "read:goals", label: "Goals", clause: "savings targets & progress" },
  { id: "read:forecast", label: "Forecast", clause: "the cash outlook & overdraft odds" },
  { id: "read:networth", label: "Net worth", clause: "totals & the snapshot trend" },
  { id: "read:subscriptions", label: "Subscriptions", clause: "detected recurring charges" },
  { id: "read:scenarios", label: "Scenarios", clause: "what-if projections, never committed" },
  { id: "read:context", label: "Context", clause: "a composed read-only snapshot" },
];

const TTL_OPTIONS = [
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
  { label: "1 year", value: 365 },
];

type Status = "live" | "revoked" | "expired";

function statusOf(k: KeyMeta): Status {
  if (k.revoked) return "revoked";
  if (k.expires_at && new Date(k.expires_at).getTime() < Date.now()) return "expired";
  return "live";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function relTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diff / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return fmtDate(iso);
}

export function AgentKeys() {
  const { toast } = useToast();
  const mcpEnabled = useStore((s) => s.mcpEnabled);
  const settingsLoaded = useStore((s) => s.settingsLoaded);
  const settingsError = useStore((s) => s.settingsError);
  const fetchUserSettings = useStore((s) => s.fetchUserSettings);
  const [keys, setKeys] = useState<KeyMeta[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [keysFailed, setKeysFailed] = useState(false);
  const [minted, setMinted] = useState<MintedKey | null>(null);
  const [selectedScopes, setSelectedScopes] = useState<Set<string>>(
    () => new Set(["read:accounts", "read:transactions"])
  );
  const createButtonRef = useRef<HTMLButtonElement>(null);

  const refresh = useCallback(async () => {
    setKeysFailed(false);
    try {
      const res = await api.get<KeyMeta[]>("/mcp-keys/");
      setKeys(Array.isArray(res.data) ? res.data : []);
    } catch {
      setKeysFailed(true);
      toast({ title: "Could not load keys", variant: "destructive" });
    } finally {
      setLoaded(true);
    }
  }, [toast]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const liveCount = useMemo(
    () => keys.filter((k) => statusOf(k) === "live").length,
    [keys]
  );

  return (
    <section className="relative">
      <BureauMasthead liveCount={liveCount} />

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
        {settingsLoaded && mcpEnabled ? (
          <IssueWrit
            scopes={selectedScopes}
            setScopes={setSelectedScopes}
            createButtonRef={createButtonRef}
            onIssued={(m) => { setMinted(m); refresh(); }}
          />
        ) : (
          <ConnectionUnavailable
            known={settingsLoaded}
            failed={settingsError}
            onRetry={() => void fetchUserSettings()}
          />
        )}
        <KeyRegister
          keys={keys}
          loaded={loaded}
          failed={keysFailed}
          onRetry={refresh}
          onRevoke={refresh}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <CapabilityStamps grantedScopes={[...selectedScopes]} />
        <AuditLedger />
      </div>

      {minted && (
        <RevealNote
          minted={minted}
          returnFocusRef={createButtonRef}
          onClose={() => {
            setMinted(null);
            window.setTimeout(() => createButtonRef.current?.focus(), 0);
          }}
        />
      )}
    </section>
  );
}

/* ── Sealed shut: the MCP surface is not enabled on this instance ──────────── */
function ConnectionUnavailable({
  known,
  failed,
  onRetry,
}: {
  known: boolean;
  failed: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="plate relative overflow-hidden bg-card px-6 py-12 text-center">
      <div className="pointer-events-none absolute -right-6 -top-8 text-gold/10">
        <CornerRosette size={120} seed={42} />
      </div>
      <div className="relative mx-auto grid max-w-md place-items-center">
        <div className="text-rule-strong/40">
          <CornerRosette size={72} seed={5} />
        </div>
        <p className="mt-3 font-display text-xl">
          {failed
            ? "Could not check connection availability"
            : known
              ? "New connections are disabled"
              : "Checking connection availability"}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {failed
            ? "Key creation remains unavailable until the signed-in settings check succeeds. Existing keys and recorded activity remain available."
            : known
            ? "You cannot create a new key on this instance. Existing keys and recorded activity remain available to review or revoke."
            : "Key creation stays unavailable until the signed-in settings check finishes."}
        </p>
        {failed && (
          <button
            type="button"
            onClick={onRetry}
            className="press mt-4 min-h-11 border border-rule px-4 font-sans text-sm font-semibold"
          >
            Retry availability check
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Masthead: the department header, set like a banknote's title bar ─────── */
function BureauMasthead({ liveCount }: { liveCount: number }) {
  return (
    <header className="plate relative overflow-hidden bg-card px-6 py-5">
      <div className="pointer-events-none absolute -right-6 -top-8 text-gold/15">
        <CornerRosette size={120} seed={42} />
      </div>
      <div className="relative flex items-center justify-between gap-4">
        <div>
          <p className="dept-label">AI connections · advanced integration</p>
          <h3 className="mt-1 font-display text-2xl leading-tight tracking-tight">
            Claude Code / developer connection
          </h3>
          <p className="mt-1 max-w-md text-sm text-muted-foreground">
            Create a scoped, revocable bearer key for an HTTP MCP client. This
            connection can read only the permissions you select; it cannot move money.
          </p>
        </div>
        <div className="hidden shrink-0 text-right sm:block">
          <p className="intaglio text-4xl leading-none ledger-figures">{liveCount}</p>
          <p className="dept-label mt-1">in force</p>
        </div>
      </div>
      <div className="relative mt-4 -mx-6 text-gold/40">
        <GuillocheBand height={14} waves={5} seed={9} />
      </div>
    </header>
  );
}

/* ── The issuance writ: name, scope clauses, term ─────────────────────────── */
function IssueWrit({
  onIssued,
  scopes,
  setScopes,
  createButtonRef,
}: {
  onIssued: (m: MintedKey) => void;
  scopes: Set<string>;
  setScopes: React.Dispatch<React.SetStateAction<Set<string>>>;
  createButtonRef: React.RefObject<HTMLButtonElement>;
}) {
  const { toast } = useToast();
  const [name, setName] = useState("");
  const [ttl, setTtl] = useState(90);
  const [issuing, setIssuing] = useState(false);

  const toggle = (id: string) =>
    setScopes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      toast({ title: "Name the bearer", description: "Who is this key for?", variant: "destructive" });
      return;
    }
    if (scopes.size === 0) {
      toast({ title: "Grant at least one clause", variant: "destructive" });
      return;
    }
    setIssuing(true);
    try {
      const res = await api.post<MintedKey>("/mcp-keys/", {
        name: name.trim(),
        scopes: [...scopes],
        ttl_days: ttl,
      });
      onIssued(res.data);
      setName("");
      toast({ title: "Key sealed", description: "Copy it now — it is shown once." });
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Could not issue the key.";
      toast({ title: "Issuance refused", description: detail, variant: "destructive" });
    } finally {
      setIssuing(false);
    }
  };

  return (
    <form onSubmit={submit} className="plate relative bg-card p-5">
      <div className="section-rule mb-4">
        <span className="dept-label whitespace-nowrap">Issue a Writ</span>
      </div>

      {/* bearer */}
      <label className="block">
        <span className="dept-label">Bearer</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Claude Code on my laptop"
          maxLength={64}
          className={cn(
            "mt-1.5 w-full border-b border-rule bg-transparent px-0 py-1.5",
            "font-display text-lg placeholder:text-muted-foreground/50",
            "focus:border-gold focus:outline-none focus-visible:shadow-none"
          )}
        />
      </label>

      {/* scope clauses */}
      <fieldset className="mt-5">
        <legend className="dept-label mb-2">Clauses granted</legend>
        <div className="space-y-px">
          {SCOPES.map((s) => {
            const on = scopes.has(s.id);
            return (
              <label
                key={s.id}
                className={cn(
                  "group flex min-h-11 w-full cursor-pointer items-center gap-3 border border-transparent px-2 py-2 text-left transition-colors",
                  on ? "bg-gold-soft/60" : "hover:bg-ink-wash"
                )}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => toggle(s.id)}
                  className="h-5 w-5 shrink-0 accent-[hsl(var(--gold))]"
                />
                <span
                  className="min-w-0 flex-1"
                >
                  <span className="block font-sans text-sm font-semibold">{s.label}</span>
                  <span className="block truncate text-xs text-muted-foreground">{s.clause}</span>
                </span>
                <code className="hidden shrink-0 font-mono text-[10px] text-muted-foreground/70 sm:block">
                  {s.id}
                </code>
              </label>
            );
          })}
        </div>
      </fieldset>

      {/* term */}
      <div className="mt-5">
        <span className="dept-label">Term of validity</span>
        <div className="mt-1.5 grid grid-cols-3 gap-1" role="radiogroup" aria-label="Key duration">
          {TTL_OPTIONS.map((opt) => (
            <label
              key={opt.value}
              className={cn(
                "press flex min-h-11 cursor-pointer items-center justify-center gap-1.5 border px-2 py-1.5 font-mono text-[11px] uppercase tracking-wide transition-colors",
                ttl === opt.value
                  ? "border-rule-strong bg-primary text-primary-foreground"
                  : "border-rule text-muted-foreground hover:border-rule-strong hover:text-foreground"
              )}
            >
              <input
                type="radio"
                name="key-duration"
                value={opt.value}
                checked={ttl === opt.value}
                onChange={() => setTtl(opt.value)}
                className="sr-only"
              />
              {opt.label}
            </label>
          ))}
        </div>
      </div>

      <button
        ref={createButtonRef}
        type="submit"
        disabled={issuing}
        className={cn(
          "press mt-6 flex w-full items-center justify-center gap-2 border border-rule-strong bg-primary py-2.5",
          "font-sans text-sm font-semibold uppercase tracking-[0.18em] text-primary-foreground",
          "disabled:opacity-60"
        )}
      >
        {issuing ? "Sealing…" : "Seal & Issue"}
        {!issuing && <span aria-hidden className="text-gold">✦</span>}
      </button>
      <p className="mt-2 text-center text-[11px] text-muted-foreground">
        A connected provider may copy data returned under selected permissions.
        Revocation stops future access, but cannot delete copies already received.
      </p>
    </form>
  );
}

/* ── The register: issued keys as a ruled ledger of certificates ──────────── */
function KeyRegister({
  keys,
  loaded,
  failed,
  onRetry,
  onRevoke,
}: {
  keys: KeyMeta[];
  loaded: boolean;
  failed: boolean;
  onRetry: () => void;
  onRevoke: () => void;
}) {
  return (
    <div className="plate relative bg-card p-5">
      <div className="section-rule mb-4">
        <span className="dept-label whitespace-nowrap">The Register</span>
      </div>

      {!loaded ? (
        <RegisterSkeleton />
      ) : failed ? (
        <div className="grid place-items-center py-12 text-center" role="alert">
          <p className="font-display text-base">Could not load existing keys</p>
          <button
            type="button"
            onClick={onRetry}
            className="press mt-4 min-h-11 border border-rule px-4 font-sans text-sm font-semibold"
          >
            Retry
          </button>
        </div>
      ) : keys.length === 0 ? (
        <EmptyRegister />
      ) : (
        <ul>
          {keys.map((k, i) => (
            <KeyRow key={k.id} k={k} index={i} onRevoke={onRevoke} />
          ))}
        </ul>
      )}
    </div>
  );
}

function KeyRow({ k, index, onRevoke }: { k: KeyMeta; index: number; onRevoke: () => void }) {
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const status = statusOf(k);
  const scopeList = k.scopes.split(",").map((s) => s.trim()).filter(Boolean);
  const dimmed = status !== "live";

  const revoke = async () => {
    if (!confirm(`Revoke "${k.name}"? Any agent using it loses access immediately.`)) return;
    setBusy(true);
    try {
      await api.delete(`/mcp-keys/${k.id}/`);
      toast({ title: "Key voided", description: `"${k.name}" no longer opens the door.` });
      onRevoke();
    } catch {
      toast({ title: "Could not revoke", variant: "destructive" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <li
      className={cn(
        "ledger-row animate-rise-in flex items-center gap-4 py-3.5",
        dimmed && "opacity-55"
      )}
      style={{ animationDelay: `${Math.min(index, 6) * 55}ms` }}
    >
      {/* seal */}
      <div className="relative shrink-0">
        <Seal
          size={52}
          tone={status === "live" ? "wax" : status === "revoked" ? "void" : "wax"}
          label={`${k.name} · MCP`}
        />
      </div>

      {/* particulars */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate font-display text-base font-semibold leading-tight">{k.name}</p>
          <StatusStamp status={status} />
        </div>
        <p className="mt-0.5 font-mono text-xs text-muted-foreground">
          {k.key_prefix}<span className="text-muted-foreground/40">{"·".repeat(8)}</span>
        </p>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {scopeList.map((s) => (
            <span
              key={s}
              className="border border-rule px-1.5 py-px font-mono text-[10px] text-muted-foreground"
            >
              {s.replace("read:", "")}
            </span>
          ))}
        </div>
      </div>

      {/* dossier */}
      <dl className="hidden shrink-0 text-right text-[11px] leading-tight text-muted-foreground sm:block">
        <div><dt className="inline dept-label">Issued </dt><dd className="inline tabular">{fmtDate(k.created_at)}</dd></div>
        <div><dt className="inline dept-label">Used </dt><dd className="inline tabular">{relTime(k.last_used_at)}</dd></div>
        <div><dt className="inline dept-label">Expires </dt><dd className="inline tabular">{k.expires_at ? fmtDate(k.expires_at) : "never"}</dd></div>
      </dl>

      {/* action */}
      <div className="shrink-0">
        {status === "live" ? (
          <button
            onClick={revoke}
            disabled={busy}
            className={cn(
              "press border border-debit/50 px-3 py-1.5 font-sans text-xs font-semibold uppercase tracking-wider",
              "text-debit transition-colors hover:bg-debit hover:text-destructive-foreground disabled:opacity-50"
            )}
          >
            {busy ? "…" : "Void"}
          </button>
        ) : (
          <span className="manicule font-mono text-xs text-muted-foreground">☞</span>
        )}
      </div>
    </li>
  );
}

function StatusStamp({ status }: { status: Status }) {
  if (status === "live")
    return <Stamp variant="credit" still>In Force</Stamp>;
  if (status === "revoked")
    return <Stamp variant="debit" still>Voided</Stamp>;
  return <Stamp variant="ink" still>Lapsed</Stamp>;
}

function EmptyRegister() {
  return (
    <div className="grid place-items-center py-14 text-center">
      <div className="text-rule-strong/40">
        <CornerRosette size={72} seed={7} />
      </div>
      <p className="mt-3 font-display text-lg">No writs on file</p>
      <p className="mt-1 max-w-xs text-sm text-muted-foreground">
        Issue your first Letter of Marque to let an AI agent read your ledger
        through the MCP vault.
      </p>
    </div>
  );
}

function RegisterSkeleton() {
  return (
    <ul className="space-y-3">
      {[0, 1].map((i) => (
        <li key={i} className="flex items-center gap-4 py-3.5">
          <div className="h-[52px] w-[52px] shrink-0 rounded-full bg-muted/60" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-40 bg-muted/60" />
            <div className="h-3 w-28 bg-muted/40" />
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ── The one-time reveal: a perforated bearer note you copy once ──────────── */
function RevealNote({
  minted,
  onClose,
  returnFocusRef,
}: {
  minted: MintedKey;
  onClose: () => void;
  returnFocusRef: React.RefObject<HTMLButtonElement>;
}) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);
  const [copiedSetup, setCopiedSetup] = useState(false);
  const secretRef = useRef<HTMLElement>(null);

  // The client-side half of the connection: the mounted MCP endpoint plus the
  // bearer header. Written out once, alongside the key, because this is the only
  // moment the raw key exists outside the hash.
  //
  // The trailing slash is load-bearing. The MCP app is mounted at "/mcp", and a
  // request to the bare path falls through to the SPA's static catch-all and
  // comes back as index.html — a client pasting it would get HTML instead of a
  // handshake. "/mcp/" hits the mount and answers 401 until a key is presented.
  const setup = useMemo(
    () =>
      JSON.stringify(
        {
          mcpServers: {
            ledger: {
              type: "http",
              url: `${window.location.origin}/mcp/`,
              headers: { Authorization: `Bearer ${minted.raw_key}` },
            },
          },
        },
        null,
        2
      ),
    [minted.raw_key]
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(minted.raw_key);
      setCopied(true);
      toast({ title: "Copied to clipboard" });
      setTimeout(() => setCopied(false), 2200);
    } catch {
      toast({ title: "Copy failed — select it manually", variant: "destructive" });
    }
  };

  const copySetup = async () => {
    try {
      await navigator.clipboard.writeText(setup);
      setCopiedSetup(true);
      toast({ title: "Connection copied" });
      setTimeout(() => setCopiedSetup(false), 2200);
    } catch {
      toast({ title: "Copy failed — select it manually", variant: "destructive" });
    }
  };

  return (
    <Dialog open>
      <DialogContent
        className="plate max-h-[92vh] w-[calc(100vw-2rem)] max-w-lg overflow-y-auto bg-card p-0"
        hideClose
        onPointerDownOutside={(event) => event.preventDefault()}
        onEscapeKeyDown={(event) => event.preventDefault()}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          secretRef.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          returnFocusRef.current?.focus();
        }}
      >
        <DialogTitle className="sr-only">Your new AI connection key</DialogTitle>
        <DialogDescription className="sr-only">
          Copy the one-time key and Claude Code HTTP configuration before closing.
        </DialogDescription>
        {/* guilloché security strip */}
        <div className="text-gold/50">
          <GuillocheBand height={26} waves={6} seed={minted.id + 3} />
        </div>

        <div className="px-6 pb-6 pt-4">
          <div className="flex items-start justify-between">
            <div>
              <p className="dept-label">Bearer Instrument · Pay to the Order of</p>
              <h4 className="mt-0.5 font-display text-xl">{minted.name}</h4>
            </div>
            <Stamp variant="gold" still>Shown Once</Stamp>
          </div>

          {/* the secret */}
          <div className="mt-5 border border-rule-strong/60 bg-paper-high/60 p-px">
            <div className="border border-dashed border-rule-strong/40 p-3">
              <p className="dept-label mb-1.5">The Key — copy it now</p>
              <code
                ref={secretRef}
                tabIndex={-1}
                className="block break-all font-mono text-[13px] leading-relaxed text-foreground outline-none selection:bg-gold/40"
              >
                {minted.raw_key}
              </code>
            </div>
          </div>

          <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
            <span className="mt-px text-debit" aria-hidden>⚠</span>
            This is the only time the full key is shown. It is stored only as a
            one-way hash — we cannot recover it. Lose it and you must re-issue.
          </p>

          {/* the connection itself — endpoint + bearer, in the shape MCP clients read */}
          <div className="mt-5">
            <div className="flex items-baseline justify-between gap-3">
              <p className="dept-label">The Connection — for your client's config</p>
              <button
                onClick={copySetup}
                className={cn(
                  "press border border-rule px-2 py-1 font-mono text-[10px] uppercase tracking-wider transition-colors",
                  copiedSetup ? "border-credit text-credit" : "text-muted-foreground hover:text-foreground"
                )}
              >
                {copiedSetup ? "✓ Copied" : "Copy"}
              </button>
            </div>
            <pre className="mt-1.5 max-h-40 overflow-auto border border-rule-strong/40 bg-paper-high/60 p-3 font-mono text-[11px] leading-relaxed text-foreground selection:bg-gold/40">
              {setup}
            </pre>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              Use this HTTP transport configuration with Claude Code or another
              developer MCP client that accepts bearer headers. Consumer Claude
              and ChatGPT connectors require a separate OAuth connection.
            </p>
          </div>

          <div className="mt-5 flex items-center gap-2">
            <button
              onClick={copy}
              className={cn(
                "press flex-1 border border-rule-strong bg-primary py-2.5 font-sans text-sm font-semibold uppercase tracking-[0.18em] text-primary-foreground",
                copied && "bg-credit"
              )}
            >
              {copied ? "✓ Copied" : "Copy key"}
            </button>
            <button
              onClick={onClose}
              className="press border border-rule px-4 py-2.5 font-sans text-sm font-semibold uppercase tracking-[0.18em] text-muted-foreground hover:text-foreground"
            >
              Done
            </button>
          </div>
        </div>

        {/* microprint footer — the anti-counterfeit line */}
        <div className="microprint border-t border-rule/60 px-6 py-1.5">
          {`SEALED·AUTHORIZATION·${minted.key_prefix}·READ·ONLY·`.repeat(12)}
        </div>
      </DialogContent>
    </Dialog>
  );
}
