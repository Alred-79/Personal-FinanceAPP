import { useEffect, useState } from "react";
import { Loader2, Wand2 } from "lucide-react";
import { useStore } from "@/store/store";
import { ImportSession } from "@/types";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/useToast";
import { DocumentDropzone } from "@/components/custom/Reconciliation/DocumentDropzone";
import ReconciliationReview from "@/components/custom/Reconciliation/ReconciliationReview";
import { loadCapabilities } from "@/lib/capabilities";
import { Link } from "react-router-dom";

/**
 * The Reconciliation Desk — import a messy statement from ANY bank (even ones
 * Plaid can't reach) and watch the agent reconcile it against the statement's
 * own running balance before anything is written. Also hosts the Detangler:
 * a one-click pass that flags transfers, refunds, and duplicates already in the
 * ledger.
 */
export default function Reconcile() {
  const accounts = useStore((s) => s.accounts);
  const fetchAccounts = useStore((s) => s.fetchAccounts);
  const importText = useStore((s) => s.importText);
  const runDetangle = useStore((s) => s.runDetangle);
  const { toast } = useToast();

  const [accountId, setAccountId] = useState<number | null>(null);
  const [session, setSession] = useState<ImportSession | null>(null);
  const [pasteText, setPasteText] = useState("");
  const [pasting, setPasting] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [detangling, setDetangling] = useState(false);
  const [importAvailable, setImportAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    if (accounts.length === 0) fetchAccounts();
  }, [accounts.length, fetchAccounts]);

  useEffect(() => {
    let active = true;
    void loadCapabilities()
      .then((value) => {
        if (active) setImportAvailable(value.unstructured_import);
      })
      .catch(() => {
        if (active) setImportAvailable(false);
      });
    return () => {
      active = false;
    };
  }, []);

  // Default to the first account once they load.
  useEffect(() => {
    if (accountId === null && accounts.length > 0) setAccountId(accounts[0].id);
  }, [accountId, accounts]);

  const submitPaste = async () => {
    if (!accountId || !pasteText.trim()) return;
    setPasting(true);
    try {
      setSession(await importText(pasteText, accountId));
    } catch (error) {
      const detail =
        (error as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Could not read that text. Try pasting a cleaner copy.";
      toast({ variant: "destructive", title: "Import failed", description: detail });
    } finally {
      setPasting(false);
    }
  };

  const detangle = async () => {
    setDetangling(true);
    try {
      const flagged = await runDetangle();
      toast({
        title: flagged > 0 ? "Detangler found something" : "All clear",
        description:
          flagged > 0
            ? `Flagged ${flagged} possible transfer, refund, or duplicate — check your notifications.`
            : "No new transfers, refunds, or duplicates to untangle.",
      });
    } catch {
      toast({
        variant: "destructive",
        title: "Detangle failed",
        description: "Please try again.",
      });
    } finally {
      setDetangling(false);
    }
  };

  const reset = () => {
    setSession(null);
    setPasteText("");
  };

  return (
    <div>
      <PageHeader
        title="Reconciliation Desk"
        reference="Form XII"
        description="Import a statement from any bank — the desk reads it, reconciles it against its own running balance, and flags only what needs your eye."
      />

      {session ? (
        <ReconciliationReview
          session={session}
          onSessionChange={setSession}
          onCommitted={() => {
            toast({
              title: "Imported",
              description: "The transactions are now in your ledger.",
            });
            reset();
          }}
          onDiscarded={reset}
        />
      ) : (
        <Reveal className="grid gap-6 lg:grid-cols-3">
          <RevealItem className="lg:col-span-2">
          <Card raking className="h-full">
            <CardHeader>
              <CardTitle>Import a statement</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <label className="dept-label">Account</label>
                <Select
                  value={accountId != null ? String(accountId) : undefined}
                  onValueChange={(v) => setAccountId(Number(v))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Choose an account" />
                  </SelectTrigger>
                  <SelectContent>
                    {accounts.map((a) => (
                      <SelectItem key={a.id} value={String(a.id)}>
                        {a.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {importAvailable === null ? (
                <p className="font-sans text-sm text-muted-foreground" role="status">
                  Checking import availability…
                </p>
              ) : importAvailable ? <Tabs defaultValue="upload">
                <TabsList>
                  <TabsTrigger value="upload">Upload a file</TabsTrigger>
                  <TabsTrigger value="paste">Paste text</TabsTrigger>
                </TabsList>
                <TabsContent value="upload" className="pt-3">
                  {accountId != null && (
                    <DocumentDropzone
                      accountId={accountId}
                      onExtracted={setSession}
                      onExtracting={setExtracting}
                    />
                  )}
                  {extracting && (
                    <p className="mt-2 font-sans text-xs text-muted-foreground">
                      The desk is reading and reconciling — this can take a few seconds.
                    </p>
                  )}
                </TabsContent>
                <TabsContent value="paste" className="space-y-3 pt-3">
                  <Textarea
                    value={pasteText}
                    onChange={(e) => setPasteText(e.target.value)}
                    placeholder="Paste a list of transactions, a confirmation email, or a copied statement…"
                    rows={8}
                  />
                  <Button
                    onClick={submitPaste}
                    disabled={pasting || !pasteText.trim() || accountId == null}
                  >
                    {pasting ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Reading…
                      </>
                    ) : (
                      "Read & reconcile"
                    )}
                  </Button>
                </TabsContent>
              </Tabs> : (
                <div className="border border-rule bg-wash/40 p-4">
                  <p className="font-display text-lg">Document reading is not configured</p>
                  <p className="mt-1 font-sans text-sm text-muted-foreground">
                    This instance can still use manual accounts and transactions without an AI provider key.
                  </p>
                  <Button variant="outline" className="mt-4 min-h-11" asChild>
                    <Link to="/transactions">Add a transaction manually</Link>
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
          </RevealItem>

          {/* ── The Detangler ─────────────────────────────────────────── */}
          <RevealItem>
          <Card raking className="h-full">
            <CardHeader>
              <CardTitle>The Detangler</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="font-sans text-sm text-muted-foreground">
                Sweep your existing transactions for transfers between your own
                accounts, refunds, and duplicates — so your spending numbers are
                finally true. Nothing is changed without your say-so.
              </p>
              <Button variant="outline" onClick={detangle} disabled={detangling}>
                {detangling ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Untangling…
                  </>
                ) : (
                  <>
                    <Wand2 className="mr-2 h-4 w-4" />
                    Run the Detangler
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
          </RevealItem>
        </Reveal>
      )}
    </div>
  );
}
