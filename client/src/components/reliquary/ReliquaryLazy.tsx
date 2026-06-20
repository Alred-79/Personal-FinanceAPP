import { Component, lazy, Suspense, useMemo, type ReactNode } from "react";
import { useFlags } from "@/store/gameMode";
import ReliquaryFlat, { type ReliquaryProps } from "./ReliquaryFlat";

// The ONLY import of the 3D module — lazy, so three/R3F land in a separate async
// chunk fetched only when this renders (flag on + WebGL ok + goals present).
const Reliquary3D = lazy(() => import("./Reliquary"));

/** Cheap, cached WebGL capability probe. */
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

/** If the 3D scene throws at runtime (context loss, driver bug), fall back to
 *  the rich 2D vault rather than the app-level error screen. */
class ReliquaryBoundary extends Component<
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
 * Gate + code-split seam for the Reliquary. Off mode, no WebGL, or zero goals →
 * the flat vault (and the 3D chunk is never even fetched). Otherwise the 3D
 * scene loads behind Suspense, with the flat vault as both the loading fallback
 * and the error fallback.
 */
export default function ReliquaryLazy(props: ReliquaryProps) {
  const { reliquary } = useFlags();
  const supports = useMemo(webglSupported, []);

  if (!reliquary || !supports || props.goals.length === 0) {
    return <ReliquaryFlat {...props} />;
  }

  const flat = <ReliquaryFlat {...props} />;
  return (
    <ReliquaryBoundary fallback={flat}>
      <Suspense fallback={flat}>
        <Reliquary3D
          goals={props.goals}
          onEdit={props.onEdit}
          onDeposit={props.onDeposit}
          onWhatIf={props.onWhatIf}
        />
      </Suspense>
    </ReliquaryBoundary>
  );
}
