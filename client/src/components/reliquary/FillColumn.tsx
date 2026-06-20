import { useMemo } from "react";
import { Color } from "three";
import { Earmark } from "@/types";
import { ReliquaryColors } from "./useReliquaryColors";

/**
 * The liquid inside a phial: a stack of cylinder segments. The named earmarks
 * partition the filled height (progress); the unallocated remainder is credit-
 * green; a thin gold meniscus rings the top. Declarative geometry → R3F disposes
 * it on unmount (no manual cleanup needed).
 */
export function FillColumn({
  progress,
  amount,
  earmarks,
  colors,
  bodyH,
  radius,
}: {
  progress: number;
  amount: number;
  earmarks: Earmark[];
  colors: ReliquaryColors;
  bodyH: number;
  radius: number;
}) {
  const { segs, fillH } = useMemo(() => {
    const fill = amount > 0 ? Math.min(1, progress / amount) : 0;
    const filled = bodyH * fill;
    const out: { h: number; y0: number; color: Color }[] = [];
    if (progress > 0 && filled > 0) {
      let acc = 0;
      earmarks.forEach((e, i) => {
        const frac = Math.max(0, Math.min(1, e.amount / progress));
        const h = filled * frac;
        if (h > 0.0005) {
          out.push({ h, y0: acc, color: colors.bands[i % colors.bands.length] });
          acc += h;
        }
      });
      const remH = filled - acc;
      if (remH > 0.0005) out.push({ h: remH, y0: acc, color: colors.credit });
    }
    return { segs: out, fillH: filled };
  }, [progress, amount, earmarks, colors, bodyH]);

  const r = radius * 0.9;

  return (
    <group>
      {segs.map((b, i) => (
        <mesh key={i} position={[0, -bodyH / 2 + b.y0 + b.h / 2, 0]}>
          <cylinderGeometry args={[r, r, b.h, 28]} />
          <meshStandardMaterial color={b.color} roughness={0.55} metalness={0.05} />
        </mesh>
      ))}
      {fillH > 0.001 && (
        <mesh position={[0, -bodyH / 2 + fillH, 0]}>
          <cylinderGeometry args={[r * 1.03, r * 1.03, 0.02, 28]} />
          <meshStandardMaterial color={colors.gold} metalness={0.6} roughness={0.4} />
        </mesh>
      )}
    </group>
  );
}
