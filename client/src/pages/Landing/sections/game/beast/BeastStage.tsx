import { Component, lazy, Suspense, useMemo, type ReactNode } from "react";
import { usePointerFine, useReducedMotion } from "@/hooks/useEnvironment";
import type { BeastPhase } from "./BeastModel";

// The ONLY import of the 3D beast — lazy, so three/R3F/postprocessing + the model
// land in a separate async chunk fetched only when the beast renders in 3D.
const BeastScene = lazy(() => import("./BeastScene"));

/** Cheap WebGL capability probe (mirrors CoinSceneLazy). */
function webglSupported(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl") || c.getContext("experimental-webgl"));
  } catch {
    return false;
  }
}

/** If the 3D beast throws (context loss, shader/driver bug), fall back to the
 *  engraved SVG beast rather than the app-level error screen. */
class BeastBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * Gate + code-split seam for the 3D debt-beast. Reduced motion, coarse pointer, or
 * no WebGL → the engraved SVG beast (and the 3D chunk + model are never fetched).
 * Otherwise the scene loads behind Suspense, with the SVG beast as both the loading
 * and the error fallback.
 */
export function BeastStage({
  health,
  phase,
  hitKey,
  fallback,
}: {
  health: number;
  phase: BeastPhase;
  hitKey: number;
  fallback: ReactNode;
}) {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const supports = useMemo(webglSupported, []);

  if (reduce || !fine || !supports) return <>{fallback}</>;

  return (
    <BeastBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <BeastScene health={health} phase={phase} hitKey={hitKey} />
      </Suspense>
    </BeastBoundary>
  );
}
