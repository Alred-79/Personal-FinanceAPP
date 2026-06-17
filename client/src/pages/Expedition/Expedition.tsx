/**
 * The Expedition map (v4 §7.2, §10.1) — the month as a 3-act run, rendered
 * LINEARLY (the month is linear time). ONE component, two skins: in off/ambient
 * it reads as a plain calendar of acts + nodes; in full it adds a flavored
 * voyage map ABOVE the same act/node list (the list is authoritative and
 * identical across modes — snapshot-pair safe; only the skin/terms change).
 *
 * This is also the Forecast page's enhanced form (same data, plain skin) so the
 * "one component tree, calendar ↔ map" rule holds — exported as a shared
 * component and consumed by both routes.
 */
import { useEffect, useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
import { Reveal, RevealItem } from "@/components/motion/Reveal";
import { VoyageMap } from "@/components/custom/VoyageMap/VoyageMap";
import { useFlags, useTerm } from "@/store/gameMode";
import api from "@/lib/api";

interface MapNode {
  kind: string;
  day: string;
  label: string;
  bucket?: string;
  alert_type?: string;
}
interface Act {
  index: number;
  start: string;
  end: string;
  forks: { key: string; objective: string }[];
}
interface MapData {
  month: string;
  acts: Act[];
  nodes: MapNode[];
}

/**
 * The shared map/calendar surface. `skin` is derived from the mode flag — full
 * gets the voyage map + map terms, everyone else the plain calendar terms — but
 * the act/node DOM is identical (snapshot-pair safe).
 */
export function ExpeditionView() {
  const { terminal } = useFlags();
  const title = useTerm("expedition.title");
  const actLabel = useTerm("expedition.act");
  const [data, setData] = useState<MapData | null>(null);

  useEffect(() => {
    api
      .get("/game/expedition/")
      .then((r) => setData(r.data.map))
      .catch(() => {});
  }, []);

  const hasActs = !!data && data.acts.length > 0;

  return (
    <div data-testid="expedition-view" data-skin={terminal ? "map" : "calendar"}>
      <PageHeader title={title} description="Your month, act by act." reference="Folio VII · The Voyage" />

      {!hasActs && (
        <Card data-testid="expedition-empty">
          <CardContent className="flex flex-col items-center gap-3 py-16 text-center">
            <p className="font-display text-2xl text-muted-foreground">
              Nothing charted yet
            </p>
            <p className="max-w-md font-sans text-sm text-muted-foreground">
              Your month plots here act by act once there's a plan to map. In the
              meantime your finances live in the Ledger, Budgets, and Forecast.
            </p>
          </CardContent>
        </Card>
      )}

      {/* FULL — the voyage map sits above the authoritative act list. */}
      {hasActs && terminal && (
        <div className="mb-6 h-[220px] overflow-hidden border border-rule-strong/40 bg-wash/40">
          <VoyageMap acts={data!.acts} seed={(data!.month.length || 6) + 3} />
        </div>
      )}

      {hasActs && (
        <Reveal className="space-y-4">
          {data!.acts.map((act) => (
            <RevealItem key={act.index}>
              <Card raking data-testid="expedition-act">
                <CardContent className="pt-6">
                  <p className="dept-label mb-2 text-[11px]">
                    {actLabel.replace("{n}", String(act.index))}
                  </p>
                  <ul className="space-y-0.5">
                    {data!.nodes
                      .filter((n) => n.day >= act.start && n.day <= act.end)
                      .map((n, i) => (
                        <NodeRow key={`${n.day}-${i}`} node={n} />
                      ))}
                  </ul>
                  {act.forks.length > 0 ? (
                    <div className="mt-3 flex flex-wrap gap-2 border-t border-rule-strong/20 pt-3" data-testid="act-forks">
                      {act.forks.map((f) => (
                        <span
                          key={f.key}
                          className="border border-rule-strong/30 px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground"
                        >
                          {f.objective}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </CardContent>
              </Card>
            </RevealItem>
          ))}
        </Reveal>
      )}
    </div>
  );
}

function NodeRow({ node }: { node: MapNode }) {
  const label = useTerm(`expedition.node.${node.kind}`);
  return (
    <li data-testid={`node-${node.kind}`} className="ledger-row flex items-center justify-between py-2 text-sm">
      <span className="flex items-center gap-2 text-muted-foreground">
        <span className="manicule text-gold">☞</span>
        {node.day}
      </span>
      <span className="text-right">
        <span className="dept-label mr-2 text-[10px]">{label}</span>
        {node.label}
      </span>
    </li>
  );
}

export default function Expedition() {
  return <ExpeditionView />;
}
