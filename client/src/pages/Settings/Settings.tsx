import { useEffect, useState } from "react";
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
import { useToast } from "@/hooks/useToast";
import { useStore } from "@/store/store";
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
    <Card>
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

export default function Settings() {
  const { toast } = useToast();
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

  return (
    <>
      <PageHeader
        title="Settings"
        description="House rules for your ledger."
        reference="Folio VIII · Standing Instructions"
      />

      <Tabs defaultValue="preferences">
        <TabsList>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="accounts">Accounts</TabsTrigger>
          <TabsTrigger value="security">Security</TabsTrigger>
        </TabsList>

        {/* Preferences */}
        <TabsContent value="preferences">
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

          <Card className="mt-6">
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
        </TabsContent>

        {/* Accounts */}
        <TabsContent value="accounts">
          <Card>
            <CardHeader>
              <CardTitle>Accounts</CardTitle>
              <CardDescription>Manage your linked accounts.</CardDescription>
            </CardHeader>
            <CardContent>
              {accounts.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No accounts linked.
                </p>
              ) : (
                <ul className="divide-y">
                  {accounts.map((account) => (
                    <li
                      key={account.id}
                      className="flex items-center justify-between py-3"
                    >
                      <div>
                        <p className="font-medium">{account.name}</p>
                        <p className="text-sm text-muted-foreground capitalize">
                          {account.type}
                        </p>
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
        </TabsContent>

        {/* Security */}
        <TabsContent value="security">
          <Card>
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
        </TabsContent>
      </Tabs>
    </>
  );
}
