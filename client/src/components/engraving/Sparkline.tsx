import { useMemo } from "react";
import { cn } from "@/lib/utils";

interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  /** Draws itself in on mount with a stroke-dash sweep. */
  animate?: boolean;
  className?: string;
}

/** A fine engraved sparkline that draws itself like a pen stroke. */
export function Sparkline({
  data,
  width = 120,
  height = 32,
  animate = true,
  className,
}: SparklineProps) {
  const d = useMemo(() => {
    if (data.length < 2) return "";
    const min = Math.min(...data);
    const max = Math.max(...data);
    const span = max - min || 1;
    const pad = 2;
    const pts = data.map((v, i) => {
      const x = pad + (i / (data.length - 1)) * (width - pad * 2);
      const y = pad + (1 - (v - min) / span) * (height - pad * 2);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return `M${pts.join("L")}`;
  }, [data, width, height]);

  if (!d) return null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d={d}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.2}
        pathLength={1}
        style={
          animate
            ? {
                strokeDasharray: 1,
                strokeDashoffset: 1,
                animation: "spark-draw 1.1s cubic-bezier(0.4, 0, 0.2, 1) forwards",
              }
            : undefined
        }
      />
      <style>{`@keyframes spark-draw { to { stroke-dashoffset: 0; } }`}</style>
    </svg>
  );
}
