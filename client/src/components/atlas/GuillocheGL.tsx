import { useEffect, useRef } from "react";
import { useReducedMotion } from "@/hooks/useEnvironment";

/**
 * GuillocheGL — a full-bleed WebGL guilloché field (OGL). The engraved rosette
 * flows continuously and warps toward the cursor like a magnetic field, drawn as
 * fine interference lines in the ledger gold/teal. This is the full-mode "living
 * paper" centerpiece; it is lazy-imported and falls back to nothing on failure.
 *
 * Color law: pure background chrome (behind everything, pointer-events none,
 * aria-hidden); never near a money figure. Pauses on hidden tab; disabled under
 * reduced motion.
 *
 * The fragment shader sums several rotated sine bands (guilloché interference)
 * plus a cursor-centered radial warp, then thresholds to crisp engraved lines.
 */
const VERT = `
attribute vec2 position;
void main() { gl_Position = vec4(position, 0.0, 1.0); }
`;

const FRAG = `
precision highp float;
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uMouse;     // 0..1
uniform vec3 uInk;       // line color
uniform float uOpacity;

// rotate a 2D point
vec2 rot(vec2 p, float a){ float c=cos(a), s=sin(a); return mat2(c,-s,s,c)*p; }

void main() {
  vec2 uv = gl_FragCoord.xy / uRes;
  vec2 p = (uv - 0.5);
  p.x *= uRes.x / uRes.y;          // aspect-correct

  // cursor warp: pull the field toward the pointer
  vec2 m = (uMouse - 0.5);
  m.x *= uRes.x / uRes.y;
  float d = length(p - m);
  float warp = 0.26 * exp(-d * 2.6);
  p += normalize(p - m + 1e-4) * warp;

  float t = uTime * 0.15;
  float field = 0.0;

  // several rotated sine bands → guilloché interference
  for (int i = 0; i < 5; i++) {
    float fi = float(i);
    vec2 q = rot(p, t * (0.3 + fi * 0.12) + fi * 1.7);
    float freq = 34.0 + fi * 14.0;
    field += sin(q.x * freq + sin(q.y * (freq * 0.6) + t) * 2.2 + t * (1.0 + fi));
  }

  // radial rosette term
  float ang = atan(p.y, p.x);
  float rad = length(p);
  field += sin(rad * 120.0 - t * 2.0 + sin(ang * 9.0) * 3.0);

  // threshold the summed field into crisp engraved lines
  float line = abs(fract(field * 0.5) - 0.5);
  float ink = smoothstep(0.46, 0.5, line);
  ink = 1.0 - ink;

  // vignette so edges fade
  float vig = smoothstep(1.1, 0.2, length(p));
  float a = ink * uOpacity * vig;

  gl_FragColor = vec4(uInk, a);
}
`;

function readInk(el: Element): [number, number, number] {
  // Use --gold as the line ink; parse the resolved HSL → RGB 0..1.
  const hsl = getComputedStyle(el).getPropertyValue("--gold").trim();
  const m = hsl.match(/([\d.]+)\s+([\d.]+)%\s+([\d.]+)%/);
  if (!m) return [0.69, 0.54, 0.19];
  const h = +m[1] / 360, s = +m[2] / 100, l = +m[3] / 100;
  const k = (n: number) => (n + h * 12) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [f(0), f(8), f(4)];
}

export function GuillocheGL({
  opacity = 0.5,
  colorSource,
}: {
  opacity?: number;
  /** Element to read the live `--gold` ink from. Defaults to <html>; the landing
   *  passes its theme-journey root so the field follows the light→dark flip. */
  colorSource?: () => Element | null;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (reduce) return;
    const canvas = ref.current;
    if (!canvas) return;

    let cleanup = () => {};
    let cancelled = false;

    (async () => {
      try {
        const { Renderer, Program, Mesh, Triangle, Vec2 } = await import("ogl");
        if (cancelled) return;

        const renderer = new Renderer({
          canvas,
          alpha: true,
          dpr: Math.min(window.devicePixelRatio || 1, 2),
        });
        const gl = renderer.gl;
        gl.clearColor(0, 0, 0, 0);

        const inkEl = () => colorSource?.() ?? document.documentElement;
        const geometry = new Triangle(gl);
        const ink = readInk(inkEl());
        const program = new Program(gl, {
          vertex: VERT,
          fragment: FRAG,
          transparent: true,
          uniforms: {
            uRes: { value: new Vec2(1, 1) },
            uTime: { value: 0 },
            uMouse: { value: new Vec2(0.5, 0.5) },
            uInk: { value: ink },
            uOpacity: { value: opacity },
          },
        });
        const mesh = new Mesh(gl, { geometry, program });

        function resize() {
          renderer.setSize(window.innerWidth, window.innerHeight);
          program.uniforms.uRes.value.set(gl.drawingBufferWidth, gl.drawingBufferHeight);
        }
        resize();
        window.addEventListener("resize", resize);

        const target = new Vec2(0.5, 0.5);
        function onMove(e: PointerEvent) {
          target.set(e.clientX / window.innerWidth, 1 - e.clientY / window.innerHeight);
        }
        window.addEventListener("pointermove", onMove);

        let raf = 0;
        let running = true;
        const start = performance.now();
        function loop(now: number) {
          if (!running) return;
          program.uniforms.uTime.value = (now - start) / 1000;
          // ease the mouse uniform toward the target for momentum
          const mu = program.uniforms.uMouse.value as { x: number; y: number };
          mu.x += (target.x - mu.x) * 0.09;
          mu.y += (target.y - mu.y) * 0.09;
          // re-read ink in case the theme flipped
          const c = readInk(inkEl());
          (program.uniforms.uInk.value as number[])[0] = c[0];
          (program.uniforms.uInk.value as number[])[1] = c[1];
          (program.uniforms.uInk.value as number[])[2] = c[2];
          renderer.render({ scene: mesh });
          raf = requestAnimationFrame(loop);
        }
        function onVisibility() {
          if (document.hidden) { running = false; cancelAnimationFrame(raf); }
          else { running = true; raf = requestAnimationFrame(loop); }
        }
        document.addEventListener("visibilitychange", onVisibility);
        raf = requestAnimationFrame(loop);

        cleanup = () => {
          running = false;
          cancelAnimationFrame(raf);
          window.removeEventListener("resize", resize);
          window.removeEventListener("pointermove", onMove);
          document.removeEventListener("visibilitychange", onVisibility);
          const ext = gl.getExtension("WEBGL_lose_context");
          ext?.loseContext();
        };
      } catch {
        /* WebGL unavailable → render nothing (the CSS guilloché still covers it). */
      }
    })();

    return () => {
      cancelled = true;
      cleanup();
    };
  }, [reduce, opacity]);

  if (reduce) return null;

  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
    />
  );
}
