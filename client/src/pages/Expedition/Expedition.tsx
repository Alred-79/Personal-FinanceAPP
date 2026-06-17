/**
 * The Expedition map (v4 §7.2, §10.1) — the month as a 3-act run, rendered
 * LINEARLY (the month is linear time). ONE component, two skins: in off/ambient
 * it reads as a plain calendar of acts + nodes; in full it's the flavored map
 * with seeded creatures. The data is identical — only tokens/terms change.
 *
 * This is also the Forecast page's enhanced form (same data, plain skin) so the
 * "one component tree, calendar ↔ map" rule holds — exported as a shared
 * component and consumed by both routes.
 */
import { useEffect, useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import { Card, CardContent } from "@/components/ui/card";
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
 * gets the map terms, everyone else the plain calendar terms — but the DOM
 * structure is identical (snapshot-pair safe).
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
      <PageHeader title={title} description="Your month, act by act." />
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
      {data?.acts.map((act) => (
        <Card key={act.index} className="mb-4" data-testid="expedition-act">
          <CardContent className="pt-6">
            <p className="dept-label mb-2 text-[11px]">
              {actLabel.replace("{n}", String(act.index))}
            </p>
            <ul className="space-y-1">
              {data.nodes
                .filter((n) => n.day >= act.start && n.day <= act.end)
                .map((n, i) => (
                  <NodeRow key={`${n.day}-${i}`} node={n} />
                ))}
            </ul>
            {act.forks.length > 0 ? (
              <div className="mt-2 flex gap-2" data-testid="act-forks">
                {act.forks.map((f) => (
                  <span key={f.key} className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    {f.objective}
                  </span>
                ))}
              </div>
            ) : null}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function NodeRow({ node }: { node: MapNode }) {
  const label = useTerm(`expedition.node.${node.kind}`);
  return (
    <li data-testid={`node-${node.kind}`} className="flex justify-between text-sm">
      <span className="text-muted-foreground">{node.day}</span>
      <span>
        <span className="dept-label mr-2 text-[10px]">{label}</span>
        {node.label}
      </span>
    </li>
  );
}

export default function Expedition() {
  return <ExpeditionView />;
}
