/**
 * <ScanlineOverlay /> — a single, static CRT scanline veil for full mode.
 *
 * Rendered only when `flags.terminal` (mode === 'full'). A fixed,
 * pointer-events-none element with a `repeating-linear-gradient`; its opacity is
 * driven by the `--crt-intensity` token. There is NO animation here — a static
 * gradient is safe under `prefers-reduced-motion`; animated flicker (not built
 * in this package) is what would be motion-gated.
 */
import { useFlags } from "@/store/gameMode";

export function ScanlineOverlay() {
  const { terminal } = useFlags();
  if (!terminal) return null;

  return (
    <div
      data-testid="scanline-overlay"
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 z-[100]"
      style={{
        // Opacity scales with the mode's CRT intensity token (0 in off/ambient,
        // 1 in full). Capped low so the veil never fights the ledger figures.
        opacity: "calc(var(--crt-intensity, 0) * 0.06)",
        backgroundImage:
          "repeating-linear-gradient(to bottom, rgba(0,0,0,0.5) 0px, rgba(0,0,0,0.5) 1px, transparent 1px, transparent 3px)",
      }}
    />
  );
}

export default ScanlineOverlay;
