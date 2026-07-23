import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "@/components/layout/PageHeader";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/useToast";
import { useStore } from "@/store/store";
import { IntensitySelector } from "@/components/custom/IntensitySelector/IntensitySelector";
import { AgentKeys } from "@/components/custom/AgentKeys/AgentKeys";
import { StandingOrders } from "@/components/custom/StandingOrders/StandingOrders";
import { LearnedMemory } from "@/components/custom/LearnedMemory/LearnedMemory";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { SectionRule } from "@/components/engraving/SectionRule";
import { WhatWeDontDo } from "@/components/custom/Trust/WhatWeDontDo";
import api from "@/lib/api";

/**
 * A single "edit a percentage, then save" card. Both the spend warning and the
 * savings target are the same shape, so they share this component.
 */
function PercentSetting({
  title,
  description,
  value,
  onSave,
}: {
  title: string;
  description: string;
  value: number;
  onSave: (value: number) => Promise<void>;
}) {
  const { toast } = useToast();
  const [input, setInput] = useState<string>(String(value));
  const [saving, setSaving] = useState(false);

  // Keep the input in sync if the stored value loads/changes after mount.
  useEffect(() => {
    setInput(String(value));
  }, [value]);

  const handleSave = async () => {
    const val = parseInt(input, 10);
    if (isNaN(val) || val < 0 || val > 100) {
      toast({
        title: "Invalid value",
        description: "Enter a value between 0 and 100.",
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    try {
      await onSave(val);
      toast({ title: "Saved", description: `${title} updated.` });
    } catch {
      toast({
        title: "Failed to save",
        description: `Could not update ${title.toLowerCase()}.`,
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card raking className="h-full">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-3">
          <Input
            type="number"
            min={0}
            max={100}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="w-24"
          />
          <span className="text-muted-foreground">%</span>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * Pillar 2B — the bounded auto-execute threshold. An auto-fund rule that earmarks
 * at or below this dollar amount fires silently; above it the assistant surfaces a
 * one-tap proposal instead. Self-contained (reads/writes `/settings/` directly,
 * like the AI-model card) so it needs no store plumbing. Virtual money only.
 */
function AutoExecuteThreshold() {
  const { toast } = useToast();
  const [input, setInput] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .get("/settings/")
      .then((res) => {
        const v = res.data?.preferences?.auto_execute_threshold;
        setInput(v != null ? String(v) : "100");
        setLoaded(true);
      })
      .catch(() => {
        setInput("100");
        setLoaded(true);
      });
  }, []);

  const handleSave = async () => {
    const val = parseFloat(input);
    if (isNaN(val) || val < 0) {
      toast({
        title: "Invalid value",
        description: "Enter a dollar amount of 0 or more.",
        variant: "destructive",
      });
      return;
    }
    setSaving(true);
    try {
      await api.put("/settings/preferences/", {
        auto_execute_threshold: val,
      });
      toast({ title: "Saved", description: "Auto-execute threshold updated." });
    } catch {
      toast({
        title: "Failed to save",
        description: "Could not update the threshold.",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card raking>
      <CardHeader>
        <CardTitle>Auto-fund threshold</CardTitle>
        <CardDescription>
          Auto-fund rules at or below this amount set money aside silently. Above
          it, the assistant asks you to approve each time. This only moves your
          own virtual earmarks — never real bank money.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground">$</span>
          <Input
            type="number"
            min={0}
            step="1"
            value={input}
            disabled={!loaded}
            onChange={(e) => setInput(e.target.value)}
            className="w-32"
            aria-label="Auto-fund threshold in dollars"
          />
          <Button size="sm" onClick={handleSave} disabled={saving || !loaded}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/** The folios, in tab order — also the allow-list for the ?tab= deep link. */
const TABS = [
  "preferences",
  "automation",
  "memory",
  "accounts",
  "agent-keys",
  "security",
];

export default function Settings() {
  const { toast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const {
    warningPosition,
    savingsPercent,
    settingsLoaded,
    accounts,
    accountsLoaded,
    fetchUserSettings,
    fetchAccounts,
    updateWarningPosition,
    updateSavingsPercent,
    deleteAccount,
    changePassword,
    selfEmployed,
    setSelfEmployed,
  } = useStore();

  // Read-only AI model info from the /settings endpoint.
  const [aiModel, setAiModel] = useState<string | null>(null);

  // Password change state
  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [pwSaving, setPwSaving] = useState(false);

  useEffect(() => {
    if (!settingsLoaded) fetchUserSettings();
    if (!accountsLoaded) fetchAccounts();
  }, [settingsLoaded, accountsLoaded, fetchUserSettings, fetchAccounts]);

  useEffect(() => {
    api
      .get("/settings/")
      .then((res) => setAiModel(res.data?.ai?.model ?? null))
      .catch(() => setAiModel(null));
  }, []);

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();
    if (newPw !== confirmPw) {
      toast({
        title: "Passwords do not match",
        description: "New password and confirmation must match.",
        variant: "destructive",
      });
      return;
    }
    if (newPw.length < 8) {
      toast({
        title: "Password too short",
        description: "New password must be at least 8 characters.",
        variant: "destructive",
      });
      return;
    }
    setPwSaving(true);
    try {
      await changePassword(currentPw, newPw);
      toast({ title: "Password updated" });
      setCurrentPw("");
      setNewPw("");
      setConfirmPw("");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail || "Failed to update password.";
      toast({
        title: "Failed to update password",
        description: msg,
        variant: "destructive",
      });
    } finally {
      setPwSaving(false);
    }
  };

  const handleDeleteAccount = async (accountId: number) => {
    if (!confirm("Delete this account and all its transactions?")) return;
    await deleteAccount(accountId);
  };

  // The open folio is addressable: /settings?tab=agent-keys lands straight on the
  // Bureau, so the landing page's "Connect your AI" can point at it through login.
  const tab = TABS.includes(searchParams.get("tab") ?? "")
    ? (searchParams.get("tab") as string)
    : "preferences";

  return (
    <>
      <PageHeader
        title="Settings"
        description="House rules for your ledger."
        reference="Folio VIII · Standing Instructions"
      />

      <Tabs
        value={tab}
        onValueChange={(v) =>
          setSearchParams(v === "preferences" ? {} : { tab: v }, { replace: true })
        }
      >
        <TabsList>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="automation">Automation</TabsTrigger>
          <TabsTrigger value="memory">Memory</TabsTrigger>
          <TabsTrigger value="accounts">Accounts</TabsTrigger>
          <TabsTrigger value="agent-keys">AI connections</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
        </TabsList>

        {/* Preferences */}
        <TabsContent value="preferences">
          <Reveal className="space-y-8">
            <RevealItem>
              <SectionRule className="mb-4">Thresholds</SectionRule>
              <div className="grid gap-6 sm:grid-cols-2">
                <PercentSetting
                  title="Spend warning"
                  description="Alert threshold for safe to spend tracking (0 to 100%)."
                  value={warningPosition}
                  onSave={updateWarningPosition}
                />
                <PercentSetting
                  title="Savings target"
                  description="Portion of income set aside (0 to 100%)."
                  value={savingsPercent}
                  onSave={updateSavingsPercent}
                />
              </div>
            </RevealItem>

            <RevealItem>
              <SectionRule className="mb-4">Work &amp; taxes</SectionRule>
              <Card raking>
                <CardHeader>
                  <CardTitle>I&rsquo;m self-employed</CardTitle>
                  <CardDescription>
                    1099, freelance, contractor, or a side gig. Turn this on to lead
                    your home screen with your tax reserve, your typical month, and the
                    next quarterly estimate. We estimate and track; you make the moves.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="flex items-center justify-between gap-4">
                    <Label htmlFor="self-employed-toggle" className="text-sm text-muted-foreground">
                      Foreground the freelancer surfaces
                    </Label>
                    <Switch
                      id="self-employed-toggle"
                      checked={selfEmployed === true}
                      onCheckedChange={(v) => setSelfEmployed(v)}
                    />
                  </div>
                </CardContent>
              </Card>
            </RevealItem>

            <RevealItem>
              <SectionRule className="mb-4">Atmosphere</SectionRule>
              <Card raking>
                <CardContent className="pt-6">
                  <IntensitySelector />
                </CardContent>
              </Card>
            </RevealItem>

            <RevealItem>
              <SectionRule className="mb-4">Assistant</SectionRule>
              <Card raking>
                <CardHeader>
                  <CardTitle>AI assistant</CardTitle>
                  <CardDescription>
                    The model powering the in-app assistant.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm">
                    Current model:{" "}
                    <span className="font-mono">{aiModel ?? "…"}</span>
                  </p>
                </CardContent>
              </Card>
            </RevealItem>
          </Reveal>
        </TabsContent>

        {/* Accounts */}
        <TabsContent value="accounts">
          <Reveal>
            <RevealItem>
              <Card raking>
                <CardHeader>
                  <CardTitle>Accounts</CardTitle>
                  <CardDescription>
                    Manage your linked accounts.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {accounts.length === 0 ? (
                    <p className="text-sm italic text-muted-foreground">
                      No accounts linked. Link a bank to begin the register.
                    </p>
                  ) : (
                    <ul>
                      {accounts.map((account) => (
                        <li
                          key={account.id}
                          className="ledger-row flex items-center justify-between py-3"
                        >
                          <div className="flex items-center gap-3">
                            <span className="manicule" aria-hidden>
                              ☞
                            </span>
                            <div>
                              <p className="font-medium">{account.name}</p>
                              <p className="text-sm capitalize text-muted-foreground">
                                {account.type}
                              </p>
                            </div>
                          </div>
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => handleDeleteAccount(account.id)}
                          >
                            Remove
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </RevealItem>
          </Reveal>
        </TabsContent>

        {/* Automation — standing-order rules (categorize / notify) */}
        <TabsContent value="automation">
          <Reveal className="space-y-6">
            <RevealItem>
              <StandingOrders />
            </RevealItem>
            <RevealItem>
              <AutoExecuteThreshold />
            </RevealItem>
          </Reveal>
        </TabsContent>

        <TabsContent value="memory">
          <Reveal>
            <RevealItem>
              <LearnedMemory />
            </RevealItem>
          </Reveal>
        </TabsContent>

        {/* Agent Keys — MCP capability key management */}
        <TabsContent value="agent-keys">
          <Reveal>
            <RevealItem>
              <AgentKeys />
            </RevealItem>
          </Reveal>
        </TabsContent>

        {/* Security */}
        <TabsContent value="security">
          <Reveal className="space-y-8">
           <RevealItem>
            <SectionRule className="mb-4">Our promises</SectionRule>
            <WhatWeDontDo />
           </RevealItem>
           <RevealItem>
            <Card raking>
            <CardHeader>
              <CardTitle>Change password</CardTitle>
              <CardDescription>Update your login password.</CardDescription>
            </CardHeader>
            <CardContent>
              <form
                onSubmit={handlePasswordChange}
                className="flex flex-col gap-4 max-w-sm"
              >
                <div className="flex flex-col gap-1">
                  <Label htmlFor="current-pw">Current password</Label>
                  <Input
                    id="current-pw"
                    type="password"
                    value={currentPw}
                    onChange={(e) => setCurrentPw(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="new-pw">New password</Label>
                  <Input
                    id="new-pw"
                    type="password"
                    value={newPw}
                    onChange={(e) => setNewPw(e.target.value)}
                    required
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="confirm-pw">Confirm new password</Label>
                  <Input
                    id="confirm-pw"
                    type="password"
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    required
                  />
                </div>
                <Button
                  type="submit"
                  disabled={pwSaving}
                  className="self-start"
                >
                  {pwSaving ? "Updating…" : "Update password"}
                </Button>
              </form>
            </CardContent>
            </Card>
           </RevealItem>
          </Reveal>
        </TabsContent>
      </Tabs>
    </>
  );
}
