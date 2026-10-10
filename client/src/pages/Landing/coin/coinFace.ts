/**
 * Canvas generators for the coin's engraved relief, used as bump / roughness maps
 * on the gold material. Pure DOM canvas — no `three` import, so three stays in the
 * lazy 3D chunk. Grayscale: mid-gray (#808080) is zero height; lighter is raised,
 * darker is recessed.
 */

function drawArcText(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  cy: number,
  radius: number,
  fontSize: number,
  centerAngle: number,
  clockwise: boolean
) {
  ctx.save();
  ctx.fillStyle = "#d6d6d6";
  ctx.font = `600 ${fontSize}px "Spline Sans Mono", ui-monospace, monospace`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const chars = [...text];
  const step = (fontSize * 0.92) / radius;
  const dir = clockwise ? 1 : -1;
  let angle = centerAngle - (dir * (chars.length - 1) * step) / 2;
  for (const ch of chars) {
    ctx.save();
    ctx.translate(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius);
    ctx.rotate(angle + (clockwise ? Math.PI / 2 : -Math.PI / 2));
    ctx.fillText(ch, 0, 0);
    ctx.restore();
    angle += dir * step;
  }
  ctx.restore();
}

/** Which side of the coin: what the bank shows, or what is actually safe to spend. */
export type CoinSide = "balance" | "safe";

const SIDES: Record<CoinSide, { glyph: string; top: string; bottom: string }> = {
  balance: { glyph: "$", top: "· WHAT YOUR BANK SAYS ·", bottom: "· BALANCE ·" },
  safe: { glyph: "£", top: "· SAFE TO SPEND ·", bottom: "· THE LEDGER ·" },
};

/** The struck face: concentric guilloché, a beaded rim, a centre glyph, arc text.
 *  The relief is drawn a quarter-turn back, because the cylinder caps' UVs land
 *  it a quarter-turn forward once the coin is stood up to face the camera. */
export function makeCoinFaceCanvas(size = 1024, side: CoinSide = "safe"): HTMLCanvasElement {
  const { glyph, top, bottom } = SIDES[side];
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const ctx = c.getContext("2d")!;
  const cx = size / 2;
  const cy = size / 2;
  const R = size * 0.42;

  ctx.fillStyle = "#808080";
  ctx.fillRect(0, 0, size, size);
  ctx.translate(cx, cy);
  ctx.rotate(-Math.PI / 2);
  ctx.translate(-cx, -cy);

  // concentric guilloché — perturbed near-circles
  ctx.lineWidth = Math.max(1, size / 850);
  for (let ring = 0; ring < 48; ring++) {
    const base = R * (0.34 + (ring / 48) * 0.62);
    const k = 5 + (ring % 8);
    const amp = R * 0.01 * (1 + (ring % 3));
    ctx.beginPath();
    for (let a = 0; a <= Math.PI * 2 + 0.05; a += 0.025) {
      const rr = base + Math.sin(a * k + ring * 0.7) * amp;
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr;
      if (a === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = ring % 2 ? "#9c9c9c" : "#666666";
    ctx.stroke();
  }

  // beaded outer rim
  ctx.fillStyle = "#b0b0b0";
  const beads = 132;
  const beadR = R * 1.02;
  for (let i = 0; i < beads; i++) {
    const a = (i / beads) * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * beadR, cy + Math.sin(a) * beadR, size * 0.0055, 0, Math.PI * 2);
    ctx.fill();
  }
  // rim hairlines
  ctx.strokeStyle = "#5a5a5a";
  ctx.lineWidth = Math.max(1, size / 600);
  ctx.beginPath();
  ctx.arc(cx, cy, R * 0.96, 0, Math.PI * 2);
  ctx.stroke();

  // raised centre medallion
  ctx.beginPath();
  ctx.arc(cx, cy, R * 0.34, 0, Math.PI * 2);
  ctx.fillStyle = "#888888";
  ctx.fill();
  ctx.strokeStyle = "#bdbdbd";
  ctx.stroke();

  // £ monogram (raised)
  ctx.fillStyle = "#ededed";
  ctx.font = `700 ${size * 0.32}px "Fraunces", Georgia, serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(glyph, cx, cy + size * 0.015);

  // arc legends
  const arcSize = top.length > 18 ? size * 0.044 : size * 0.052;
  drawArcText(ctx, top, cx, cy, R * 0.8, arcSize, -Math.PI / 2, true);
  drawArcText(ctx, bottom, cx, cy, R * 0.8, size * 0.052, Math.PI / 2, false);

  return c;
}

/** The milled (reeded) edge: vertical stripes wrapped around the cylinder side. */
export function makeReedCanvas(w = 1024, h = 64): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#808080";
  ctx.fillRect(0, 0, w, h);
  const reeds = 112;
  const bw = w / reeds;
  for (let i = 0; i < reeds; i++) {
    ctx.fillStyle = i % 2 ? "#a6a6a6" : "#5e5e5e";
    ctx.fillRect(i * bw, 0, bw * 0.6, h);
  }
  return c;
}
