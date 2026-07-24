import React, { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import PageHeader from "@/components/layout/PageHeader";
import { useStore } from "@/store/store";
import { formatCurrency } from "@/lib/format";
import { AnimatedNumber } from "@/components/engraving/AnimatedNumber";
import { EmptyState } from "@/components/engraving/EmptyState";
import { SectionRule } from "@/components/engraving/SectionRule";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import SubscriptionCard from "./SubscriptionCard";
import CadenceCalendar from "@/components/custom/CadenceCalendar/CadenceCalendar";
import {
  monthlyBurden,
  annualBurden,
  possibleMonthlyBurden,
  isAtRisk,
  hasLifecycleData,
} from "@/lib/subscriptions";
import { Subscription } from "@/types";
import MerchantAliasManager from "./MerchantAliasManager";

function MandateGrid({ items }: { items: Subscription[] }) {
  return (
    <Reveal className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3">
      {items.map((s) => (
        <RevealItem key={s.merchant} className="h-full">
          <SubscriptionCard sub={s} />
        </RevealItem>
      ))}
    </Reveal>
  );
}

/**
 * Standing Orders: recurring charges detected in your spending, rendered as a
 * ledger of mandates — last drawn, next due, vitality, and a running burden.
 * When the lifecycle model is active, mandates split into "active" and a calmer
 * "at risk" section (no alarm chrome — the calm is the point).
 */
const Subscriptions: React.FC = () => {
  const {
    subscriptions,
    subscriptionsLoaded,
    fetchSubscriptions,
    merchantAliasesEnabled,
  } = useStore();
  const [tab, setTab] = useState("register");

  useEffect(() => {
    fetchSubscriptions();
  }, [fetchSubscriptions]);

  const monthly = monthlyBurden(subscriptions);
  const annual = annualBurden(subscriptions);
  const possibleMonthly = possibleMonthlyBurden(subscriptions);

  const grouped = hasLifecycleData(subscriptions);
  const atRisk = grouped
    ? subscriptions
        .filter(isAtRisk)
        .sort((a, b) => (a.probability_alive ?? 1) - (b.probability_alive ?? 1))
    : [];
  const active = grouped
    ? subscriptions.filter((s) => !isAtRisk(s))
    : subscriptions;

  return (
    <>
      <PageHeader
        title="Standing Orders"
        description="Mandates drawn against your accounts on a schedule."
        reference="Folio VII · Recurring Charges"
      />

      <Tabs value={tab} onValueChange={setTab} className="space-y-6">
        <TabsList>
          <TabsTrigger value="register">Register</TabsTrigger>
          <TabsTrigger value="cadence">Cadence</TabsTrigger>
          {merchantAliasesEnabled && (
            <TabsTrigger value="merchant-groups">Merchant groups</TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="register">
          {subscriptions.length > 0 && (
            <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-8 gap-y-2 border-b border-rule-strong/30 pb-4">
              <p className="dept-label">
                {subscriptions.length} mandate
                {subscriptions.length === 1 ? "" : "s"} on file
              </p>
              <div className="flex items-baseline gap-8">
                <div className="text-right">
                  <p className="dept-label">Likely active / month</p>
                  <p className="intaglio text-3xl ink-debit">
                    <AnimatedNumber value={monthly} />
                  </p>
                </div>
                {grouped && possibleMonthly > 0 && (
                  <div className="text-right">
                    <p className="dept-label">Needs review / month</p>
                    <p className="ledger-figures text-lg text-muted-foreground">
                      {formatCurrency(possibleMonthly)}
                    </p>
                  </div>
                )}
                <div className="text-right">
                  <p className="dept-label">Projected / yr</p>
                  <p className="ledger-figures text-lg text-muted-foreground">
                    {formatCurrency(annual)}
                  </p>
                </div>
              </div>
            </div>
          )}

          {grouped && active.length > 0 && (
            <SectionRule className="mb-4">Active mandates</SectionRule>
          )}
          {active.length > 0 && <MandateGrid items={active} />}

          {atRisk.length > 0 && (
            <>
              <SectionRule className="mb-4 mt-10">
                At risk · {atRisk.length}
              </SectionRule>
              <MandateGrid items={atRisk} />
            </>
          )}

          {subscriptionsLoaded && subscriptions.length === 0 && (
            <Reveal className="grid grid-cols-1">
              <EmptyState
                seed={9}
                eyebrow="Standing Orders · None on file"
                title="No standing orders detected"
                description="Mandates are spotted automatically from your transaction history once you've linked an account and built up a few months of spending."
              />
            </Reveal>
          )}
        </TabsContent>

        <TabsContent value="cadence">
          <CadenceCalendar />
        </TabsContent>

        {merchantAliasesEnabled && (
          <TabsContent value="merchant-groups">
            <MerchantAliasManager onChanged={fetchSubscriptions} />
          </TabsContent>
        )}
      </Tabs>
    </>
  );
};

export default Subscriptions;
