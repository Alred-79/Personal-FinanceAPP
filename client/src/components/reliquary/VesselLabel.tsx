import { Html } from "@react-three/drei";
import { formatCurrency } from "@/lib/format";

/**
 * A clean-DOM caption pinned under a vessel via drei <Html>. Money/names render
 * in normal DOM (so the color law's filter:none guard applies — never painted
 * into the canvas). Non-interactive; the vessel mesh owns the clicks.
 */
export function VesselLabel({
  name,
  progress,
  amount,
  y,
}: {
  name: string;
  progress: number;
  amount: number;
  y: number;
}) {
  return (
    <Html
      position={[0, y, 0]}
      center
      zIndexRange={[20, 0]}
      className="pointer-events-none"
    >
      {/* aria-hidden lives on the DOM <div>, NOT on <Html>: drei spreads <Html>'s
          extra props onto the R3F <group>, and R3F parses the hyphen in
          `aria-hidden` as a pierced path (`group.aria.hidden`) → crashes the
          whole Canvas. Keeping it on real DOM preserves the SR intent safely. */}
      <div className="w-28 select-none text-center" aria-hidden>
        <p className="truncate font-display text-[11px] font-semibold leading-tight text-foreground">
          {name}
        </p>
        <p className="intaglio text-[12px] text-foreground">
          {formatCurrency(progress)}
        </p>
        <p className="ledger-figures text-[9px] text-muted-foreground">
          of {formatCurrency(amount)}
        </p>
      </div>
    </Html>
  );
}
