/**
 * <ClosureCard /> — the 1200×630 share image for a defeated boss (v4 §7.1).
 *
 * Client-rendered to a canvas and exported as PNG (the distribution surface).
 * Archetype-free for now: boss name, tier glyph, and duration ("defeated in 7
 * months"). ZERO dollar amounts by default — amounts appear only when the
 * `includeNumbers` toggle is on (sharing your debt figure is opt-in).
 *
 * The layout is drawn deterministically so the same inputs render the same card.
 */
import { useEffect, useRef } from "react";
import { asciiCreature } from "@/lib/asciiCreature";

export interface ClosureCardProps {
  bossName: string;
  kind: "credit_card" | "loan" | "bnpl" | "other";
  durationMonths: number;
  /** Opt-in: include the dollar amount paid off. Off by default. */
  includeNumbers?: boolean;
  amountPaidCents?: number;
  /** Tier glyph (e.g. a roman numeral or symbol) drawn beside the name. */
  tierGlyph?: string;
}

export const CARD_W = 1200;
export const CARD_H = 630;

/** Pure: the lines of text the card will draw (testable without a canvas). */
export function closureCardLines(props: ClosureCardProps): string[] {
  const lines = [
    props.tierGlyph ? `${props.tierGlyph}  ${props.bossName}` : props.bossName,
    `Defeated in ${props.durationMonths} ${
      props.durationMonths === 1 ? "month" : "months"
    }`,
  ];
  if (props.includeNumbers && props.amountPaidCents != null) {
    lines.push(`$${(props.amountPaidCents / 100).toLocaleString("en-US")} cleared`);
  }
  return lines;
}

function draw(canvas: HTMLCanvasElement, props: ClosureCardProps): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  canvas.width = CARD_W;
  canvas.height = CARD_H;

  // Ledger-paper ground.
  ctx.fillStyle = "#0f1115";
  ctx.fillRect(0, 0, CARD_W, CARD_H);
  ctx.strokeStyle = "rgba(212,175,99,0.5)";
  ctx.lineWidth = 4;
  ctx.strokeRect(24, 24, CARD_W - 48, CARD_H - 48);

  // Seeded creature art on the left, in amber.
  const art = asciiCreature({ kind: props.kind, name: props.bossName, balanceCents: props.amountPaidCents });
  ctx.fillStyle = "#d4af63";
  ctx.font = "20px monospace";
  art.forEach((row, i) => ctx.fillText(row, 64, 180 + i * 22));

  // Text block on the right.
  const lines = closureCardLines(props);
  ctx.fillStyle = "#f3efe6";
  ctx.font = "bold 64px Georgia, serif";
  ctx.fillText(lines[0], 480, 260);
  ctx.font = "36px Georgia, serif";
  lines.slice(1).forEach((l, i) => ctx.fillText(l, 480, 340 + i * 60));
}

export function ClosureCard(props: ClosureCardProps) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (ref.current) draw(ref.current, props);
  }, [props]);

  function download() {
    const url = ref.current?.toDataURL("image/png");
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.download = `${props.bossName.replace(/\s+/g, "-")}-defeated.png`;
    a.click();
  }

  return (
    <div data-testid="closure-card">
      <canvas
        ref={ref}
        data-testid="closure-canvas"
        style={{ width: "100%", maxWidth: CARD_W, aspectRatio: `${CARD_W} / ${CARD_H}` }}
      />
      <button
        data-testid="closure-download"
        onClick={download}
        className="press mt-3 border border-rule-strong/50 bg-card px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-foreground shadow-plate"
      >
        Save share image
      </button>
    </div>
  );
}

export default ClosureCard;
