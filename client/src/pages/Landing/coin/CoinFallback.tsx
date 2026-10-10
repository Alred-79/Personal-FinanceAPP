import { useReducedMotion } from "@/hooks/useEnvironment";
import type { CoinSide } from "./coinFace";

/**
 * The no-WebGL / touch / reduced-motion coin: a CSS-3D gold disc with the same
 * two faces as the 3D coin ($ = what your bank says, £ = safe to spend). Tap to
 * turn it over; under reduced motion the faces crossfade instead of rotating.
 * Decorative (aria-hidden) — the hero's labelled toggle is the accessible control.
 */
export function CoinFallback({
  side,
  onSideChange,
}: {
  side: CoinSide;
  onSideChange?: (side: CoinSide) => void;
}) {
  const reduce = useReducedMotion();
  return (
    <div
      className="coin-fallback"
      aria-hidden
      onClick={() => onSideChange?.(side === "balance" ? "safe" : "balance")}
    >
      <div className="coin-fallback__flip" data-side={side} data-reduce={reduce ? "" : undefined}>
        <div className="coin-fallback__spin" data-reduce={reduce ? "" : undefined}>
          <div className="coin-fallback__face coin-fallback__face--front">$</div>
          <div className="coin-fallback__face coin-fallback__face--back">£</div>
        </div>
      </div>
    </div>
  );
}
