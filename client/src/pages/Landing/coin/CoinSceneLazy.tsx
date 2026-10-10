import { Component, lazy, Suspense, useMemo, type ReactNode } from "react";
import { usePointerFine, useReducedMotion } from "@/hooks/useEnvironment";
import { CoinFallback } from "./CoinFallback";
import type { CoinSide } from "./coinFace";

// The ONLY import of the 3D scene — lazy, so three/R3F/postprocessing land in a
// separate async chunk fetched only when the coin actually renders in 3D.
const CoinScene = lazy(() => import("./CoinScene"));

/** Cheap WebGL capability probe (mirrors ReliquaryLazy). */
function webglSupported(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(
      c.getContext("webgl2") ||
      c.getContext("webgl") ||
      c.getContext("experimental-webgl")
    );
  } catch {
    return false;
  }
}

/** If the 3D coin throws at runtime (context loss, driver/postprocessing bug),
 *  fall back to the CSS coin rather than the app-level error screen. */
class CoinBoundary extends Component<
  { fallback: ReactNode; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * Gate + code-split seam for the hero coin. Reduced motion, touch / coarse
 * pointer, or no WebGL → the CSS coin (and the 3D chunk is never fetched).
 * Otherwise the scene loads behind Suspense, with the CSS coin as both the
 * loading and the error fallback.
 */
export function CoinStage({
  side,
  onSideChange,
}: {
  side: CoinSide;
  onSideChange?: (side: CoinSide) => void;
}) {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const supports = useMemo(webglSupported, []);

  const fallback = <CoinFallback side={side} onSideChange={onSideChange} />;
  if (reduce || !fine || !supports) return fallback;

  return (
    <CoinBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <CoinScene side={side} onSideChange={onSideChange} />
      </Suspense>
    </CoinBoundary>
  );
}
