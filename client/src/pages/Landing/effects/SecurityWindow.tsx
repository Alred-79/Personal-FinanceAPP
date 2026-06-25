import { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A polymer "security window": a frosted, sharp-cornered glass panel with an
 * engraved double frame. The guilloché field blurs through it, the way the clear
 * window of a polymer note shows the surface behind. The frosted backdrop stays
 * opaque enough that money figures inside keep their contrast (the colour/number
 * law) — verified against the field in the browser.
 */
export function SecurityWindow({
  className,
  children,
}: {
  className?: string;
  children?: ReactNode;
}) {
  return <div className={cn("security-window", className)}>{children}</div>;
}
