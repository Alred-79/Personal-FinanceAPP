import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { ArrowRight, RotateCcw } from "lucide-react";

import api from "@/lib/api";
import type { MerchantAlias, MerchantDescriptor } from "@/types";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { SectionRule } from "@/components/engraving/SectionRule";

type Props = { onChanged?: () => void | Promise<void> };

function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "response" in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } })
      .response;
    if (typeof response?.data?.detail === "string") return response.data.detail;
  }
  return "The merchant group could not be updated. Please try again.";
}

const selectClass =
  "h-9 w-full rounded-none border border-rule-strong/50 bg-card px-3 font-sans text-sm text-card-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50";

/** Compact, explicit editor for one-hop merchant grouping aliases. */
const MerchantAliasManager: React.FC<Props> = ({ onChanged }) => {
  const [aliases, setAliases] = useState<MerchantAlias[]>([]);
  const [descriptors, setDescriptors] = useState<MerchantDescriptor[]>([]);
  const [aliasDescriptor, setAliasDescriptor] = useState("");
  const [canonicalDescriptor, setCanonicalDescriptor] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    const [aliasResponse, descriptorResponse] = await Promise.all([
      api.get("/merchant-aliases/"),
      api.get("/merchant-aliases/descriptors/"),
    ]);
    setAliases(aliasResponse.data);
    setDescriptors(descriptorResponse.data);
  };

  useEffect(() => {
    let mounted = true;
    Promise.all([
      api.get("/merchant-aliases/"),
      api.get("/merchant-aliases/descriptors/"),
    ])
      .then(([aliasResponse, descriptorResponse]) => {
        if (!mounted) return;
        setAliases(aliasResponse.data);
        setDescriptors(descriptorResponse.data);
      })
      .catch((reason: unknown) => {
        if (mounted) setError(errorMessage(reason));
      });
    return () => {
      mounted = false;
    };
  }, []);

  const aliasKey = useMemo(
    () =>
      descriptors.find((item) => item.descriptor === aliasDescriptor)
        ?.normalized_key ?? "",
    [aliasDescriptor, descriptors]
  );
  const canonicalKey = useMemo(
    () =>
      descriptors.find((item) => item.descriptor === canonicalDescriptor)
        ?.normalized_key ?? "",
    [canonicalDescriptor, descriptors]
  );
  const invalidPair = Boolean(aliasKey && canonicalKey && aliasKey === canonicalKey);
  const canSubmit =
    Boolean(aliasDescriptor && canonicalDescriptor && confirmed) &&
    !invalidPair &&
    !busy;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await api.post("/merchant-aliases/", {
        alias_descriptor: aliasDescriptor,
        canonical_descriptor: canonicalDescriptor,
        confirmed: true,
      });
      await load();
      await onChanged?.();
      setAliasDescriptor("");
      setCanonicalDescriptor("");
      setConfirmed(false);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const undo = async (id: number) => {
    setBusy(true);
    setError(null);
    try {
      await api.delete(`/merchant-aliases/${id}/`);
      await load();
      await onChanged?.();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="merchant-groups-title" className="max-w-3xl">
      <div className="mb-5 max-w-2xl">
        <h2
          id="merchant-groups-title"
          className="font-display text-xl font-semibold text-foreground"
        >
          Group merchant descriptions
        </h2>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">
          Tell the ledger when two descriptions should group together. This does
          not verify a company&rsquo;s identity or change your transaction history.
        </p>
      </div>

      <form onSubmit={submit} className="space-y-4 border-y border-rule py-5">
        <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto_1fr]">
          <label className="space-y-1.5 text-sm font-medium text-foreground">
            Description to group
            <select
              aria-label="Description to group"
              className={selectClass}
              value={aliasDescriptor}
              onChange={(event) => {
                setAliasDescriptor(event.target.value);
                setConfirmed(false);
              }}
              disabled={busy}
            >
              <option value="">Choose a description</option>
              {descriptors.map((item) => (
                <option key={item.normalized_key} value={item.descriptor}>
                  {item.descriptor}
                </option>
              ))}
            </select>
          </label>
          <ArrowRight
            aria-hidden="true"
            className="mb-2 hidden h-4 w-4 text-muted-foreground sm:block"
          />
          <label className="space-y-1.5 text-sm font-medium text-foreground">
            Group under
            <select
              aria-label="Group under"
              className={selectClass}
              value={canonicalDescriptor}
              onChange={(event) => {
                setCanonicalDescriptor(event.target.value);
                setConfirmed(false);
              }}
              disabled={busy}
            >
              <option value="">Choose a canonical description</option>
              {descriptors.map((item) => (
                <option key={item.normalized_key} value={item.descriptor}>
                  {item.descriptor}
                </option>
              ))}
            </select>
          </label>
        </div>

        {aliasDescriptor && canonicalDescriptor && !invalidPair && (
          <div className="bg-wash px-3 py-2.5 text-sm text-foreground">
            Charges labeled <strong>{aliasDescriptor}</strong> will group under{" "}
            <strong>{canonicalDescriptor}</strong>.
          </div>
        )}
        {invalidPair && (
          <p role="alert" className="text-sm text-debit">
            Choose two different normalized merchant descriptions.
          </p>
        )}

        <div className="flex flex-wrap items-center justify-between gap-4">
          <label className="flex max-w-xl items-start gap-2.5 text-sm leading-5 text-muted-foreground">
            <Checkbox
              aria-label="Confirm merchant grouping"
              checked={confirmed}
              onCheckedChange={(checked) => setConfirmed(checked === true)}
              disabled={!aliasDescriptor || !canonicalDescriptor || invalidPair || busy}
            />
            <span>
              I confirm this grouping. It changes categorization lookup and
              subscription grouping only, and I can undo it.
            </span>
          </label>
          <Button type="submit" size="sm" disabled={!canSubmit}>
            {busy ? "Updating…" : "Confirm group"}
          </Button>
        </div>
        {error && (
          <p role="alert" className="text-sm text-debit">
            {error}
          </p>
        )}
      </form>

      <SectionRule className="mb-3 mt-7">Active groups</SectionRule>
      {aliases.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No merchant descriptions are grouped yet.
        </p>
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {aliases.map((item) => (
            <li
              key={item.id}
              className="flex min-h-12 items-center justify-between gap-4 py-2.5"
            >
              <p className="min-w-0 text-sm text-foreground">
                <span className="font-mono">{item.alias_key}</span>
                <ArrowRight
                  aria-label="resolves to"
                  className="mx-2 inline h-3.5 w-3.5 text-muted-foreground"
                />
                <span className="font-medium">{item.canonical_label}</span>
              </p>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => undo(item.id)}
              >
                <RotateCcw aria-hidden="true" />
                Undo
              </Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
};

export default MerchantAliasManager;
