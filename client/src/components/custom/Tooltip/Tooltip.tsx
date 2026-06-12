import { TooltipProps } from "recharts";

/** Engraved chart tooltip: a small paper chit with a hairline frame. */
const Tooltip = ({ active, payload }: TooltipProps<number, string>) => {
  if (active && payload && payload.length) {
    return (
      <div className="border border-rule-strong/50 bg-popover px-2.5 py-1.5 shadow-plate-lg">
        <p className="font-mono text-[11px] text-popover-foreground">
          <span className="text-muted-foreground">{payload[0].payload.name}</span>{" "}
          ${payload[0].value?.toLocaleString("en-US", { minimumFractionDigits: 2 })}
        </p>
      </div>
    );
  }
  return null;
};

export default Tooltip;
