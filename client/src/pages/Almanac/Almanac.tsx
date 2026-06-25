import { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import PageHeader from "@/components/layout/PageHeader";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { useStore } from "@/store/store";
import AlmanacHeatGrid from "./AlmanacHeatGrid";
import NetWorthTrend from "./NetWorthTrend";
import AllotmentReadout from "./AllotmentReadout";
import MoneyFlow from "@/components/custom/MoneyFlow/MoneyFlow";

/**
 * The Almanac — an analytical abstract of the ledger: where money flows by
 * category and over time, how net worth trends, and how much of this period's
 * paycheck allotment remains. Pure finance; renders identically in every mode.
 */
export default function Almanac() {
  const fetchNetWorth = useStore((s) => s.fetchNetWorth);
  const refreshBudgetData = useStore((s) => s.refreshBudgetData);
  const [tab, setTab] = useState("atlas");

  useEffect(() => {
    fetchNetWorth();
    refreshBudgetData();
  }, [fetchNetWorth, refreshBudgetData]);

  return (
    <>
      <PageHeader
        title="Almanac"
        description="Where your money flows, charted by category and across time."
        reference="Form XV · Analytical Abstract"
      />

      <Tabs value={tab} onValueChange={setTab} className="space-y-6">
        <TabsList>
          <TabsTrigger value="atlas">Spending Atlas</TabsTrigger>
          <TabsTrigger value="flow">Flow</TabsTrigger>
          <TabsTrigger value="networth">Net Worth</TabsTrigger>
          <TabsTrigger value="allotment">Allotment</TabsTrigger>
        </TabsList>

        <TabsContent value="flow">
          <Reveal>
            <RevealItem>
              <MoneyFlow />
            </RevealItem>
          </Reveal>
        </TabsContent>

        <TabsContent value="atlas">
          <Reveal>
            <RevealItem>
              <AlmanacHeatGrid />
            </RevealItem>
          </Reveal>
        </TabsContent>

        <TabsContent value="networth">
          <Reveal>
            <RevealItem>
              <NetWorthTrend />
            </RevealItem>
          </Reveal>
        </TabsContent>

        <TabsContent value="allotment">
          <Reveal>
            <RevealItem>
              <AllotmentReadout />
            </RevealItem>
          </Reveal>
        </TabsContent>
      </Tabs>
    </>
  );
}
