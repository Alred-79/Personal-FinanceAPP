import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * The no-WebGL / touch / reduced-motion coin: a CSS-3D gold disc that turns on
 * its axis (still on reduced motion). Mirrors the 3D coin's silhouette so the
 * hero reads the same on every device. Decorative — aria-hidden.
 */
export function CoinFallback() {
  const reduce = useReducedMotion();
  return (
    <div className="coin-fallback" aria-hidden>
      <div className="coin-fallback__spin" data-reduce={reduce ? "" : undefined}>
        <div className="coin-fallback__face coin-fallback__face--front">£</div>
        <div className="coin-fallback__face coin-fallback__face--back">£</div>
      </div>
    </div>
  );
}
