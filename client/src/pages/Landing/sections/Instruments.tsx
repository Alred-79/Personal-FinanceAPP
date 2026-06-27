import { useEffect, useRef, useState, type RefObject } from "react";
import { motion, useScroll, useTransform } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { useTilt } from "../hooks/useTilt";
import { FEATURES, type Feature } from "../data";
import { Rise, EASE } from "../shared";
import { PlateVisual } from "./instrumentVisuals";
import { AvailableWhenEnabled } from "@/components/custom/Trust/AvailableWhenEnabled";

/**
 * Scrub a plate's scene animation to its travel across the viewport: writes a
 * `--p` (0..1) custom property each frame from the element's position, so the
 * CSS flourish (paused, with a negative delay keyed off --p) unfolds exactly at
 * the pace of the scroll. Runs a rAF loop only while the element is on-screen.
 * mode "x": progress as it slides left across the filmstrip; "y": as it scrolls
 * up the grid.
 */
function useScrubVar(ref: RefObject<HTMLElement>, mode: "x" | "y", enabled = true) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return;
    let raf = 0;
    let active = false;
    const tick = () => {
      const r = el.getBoundingClientRect();
      let p: number;
      if (mode === "x") {
        const c = r.left + r.width / 2;
        p = (window.innerWidth - c) / (window.innerWidth * 0.55);
      } else {
        const c = r.top + r.height / 2;
        p = (window.innerHeight - c) / (window.innerHeight * 0.6);
      }
      el.style.setProperty("--p", Math.max(0, Math.min(1, p)).toFixed(3));
      raf = active ? requestAnimationFrame(tick) : 0;
    };
    const io = new IntersectionObserver(
      ([e]) => {
        active = e.isIntersecting;
        if (active && !raf) raf = requestAnimationFrame(tick);
      },
      { rootMargin: "30% 0px 30% 0px" }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [ref, mode, enabled]);
}

/** Shared plate content: serial, the bespoke specimen scene, title, body. */
function PlateContent({ f, index }: { f: Feature; index: number }) {
  return (
    <>
      <span className="serial absolute right-4 top-3 z-[6] font-mono text-[0.66rem] tracking-[0.16em] text-muted-foreground">
        {f.no}
      </span>
      <div className="iv-stage">
        <PlateVisual index={index} />
      </div>
      <h3 className="iv-z1 font-display text-[1.24rem] font-semibold">{f.title}</h3>
      <p className="mt-2 text-[0.9rem] leading-relaxed text-muted-foreground">{f.body}</p>
      {f.gated && (
        <div className="iv-z1 mt-3">
          <AvailableWhenEnabled detail={f.gatedNote} />
        </div>
      )}
    </>
  );
}

/** Per-plate resting depth (translateZ) inside the case — a varied near/far
 *  wave so the camera push parallaxes them against each other. */
const PLATE_DEPTH = [44, -34, 28, -44, 36, -22];

/** One plate of the case — a cursor-tracking 3D tilt card whose specimen scene
 *  lifts off the page and comes alive on hover. Each plate rests at its own depth
 *  (translateZ) and casts a real reflection on the case floor (-webkit-box-reflect),
 *  so the row reads as engraved plates seated in a recessed case, not flat cards. */
function FilmPlate({ f, index }: { f: Feature; index: number }) {
  const depth = PLATE_DEPTH[index % PLATE_DEPTH.length];
  const { ref, enabled, handlers } = useTilt(9);
  // The filmstrip only mounts for non-reduced-motion. Scrub the scene to the
  // plate's leftward travel across the strip — it unfolds at the scroll's pace.
  const wrapRef = useRef<HTMLDivElement>(null);
  useScrubVar(wrapRef, "x");
  return (
    <div
      ref={wrapRef}
      className="iv-plate3d iv-scrub shrink-0"
      style={{ transform: `translateZ(${depth}px)` }}
    >
      <div ref={ref} className="iv-tilt w-[clamp(300px,26vw,372px)]" {...handlers}>
        <article className="iv-tilt__inner plate relative bg-card p-5">
          {enabled && <span aria-hidden className="iv-sheen" />}
          <PlateContent f={f} index={index} />
        </article>
      </div>
    </div>
  );
}

/** A faint engraved guilloché bloom that forms behind the heading as the section
 *  arrives — the backdrop "tightening" into a struck seal. Pure chrome. */
function GuillocheBloom() {
  const reduce = useReducedMotion();
  return (
    <motion.svg
      className="iv-bloom"
      viewBox="0 0 400 400"
      aria-hidden
      initial={reduce ? false : { opacity: 0, scale: 0.86 }}
      whileInView={reduce ? undefined : { opacity: 0.42, scale: 1 }}
      viewport={{ once: true, margin: "-12%" }}
      transition={{ duration: 1.3, ease: EASE }}
    >
      {Array.from({ length: 8 }).map((_, i) => (
        <circle
          key={i}
          cx="200"
          cy="200"
          r={26 + i * 22}
          fill="none"
          stroke="currentColor"
          strokeWidth="0.7"
          opacity={0.5 - i * 0.045}
        />
      ))}
      {Array.from({ length: 24 }).map((_, i) => {
        const a = (i / 24) * Math.PI * 2;
        return (
          <line
            key={`r${i}`}
            x1={200 + Math.cos(a) * 40}
            y1={200 + Math.sin(a) * 40}
            x2={200 + Math.cos(a) * 196}
            y2={200 + Math.sin(a) * 196}
            stroke="currentColor"
            strokeWidth="0.4"
            opacity="0.16"
          />
        );
      })}
    </motion.svg>
  );
}

/** The section heading for the 3D case — the title is struck/inked in with an
 *  intaglio clip reveal while a guilloché bloom forms behind it, so the section
 *  ARRIVES as an engraving event rather than fading in. */
function EngravedHeading() {
  const reduce = useReducedMotion();
  const vp = { once: true, margin: "-12%" } as const;
  return (
    <div className="iv-head relative mx-auto max-w-[42rem] px-[7vw] text-center">
      <GuillocheBloom />
      <motion.p
        className="dept-label relative"
        initial={reduce ? false : { opacity: 0, y: 10 }}
        whileInView={reduce ? undefined : { opacity: 1, y: 0 }}
        viewport={vp}
        transition={{ duration: 0.6, ease: EASE }}
      >
        The Instruments
      </motion.p>
      <motion.h2
        className="iv-head__title relative mt-2 text-balance font-display font-semibold"
        style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}
        initial={reduce ? false : { clipPath: "inset(0 100% 0 0)" }}
        whileInView={reduce ? undefined : { clipPath: "inset(0 0% 0 0)" }}
        viewport={vp}
        transition={{ duration: 1.05, ease: EASE, delay: 0.12 }}
      >
        Every figure, engraved and accountable.
      </motion.h2>
      <motion.p
        className="relative mt-3 text-pretty text-[1.02rem] text-muted-foreground"
        initial={reduce ? false : { opacity: 0 }}
        whileInView={reduce ? undefined : { opacity: 1 }}
        viewport={vp}
        transition={{ duration: 0.7, ease: EASE, delay: 0.55 }}
      >
        Not another dashboard of charts you ignore. Each tool is a working
        instrument — it does one thing, shows its reasoning, and never moves
        real money without your stamp.
      </motion.p>
    </div>
  );
}

/** The section heading — shared by both the filmstrip and the grid layouts. */
function Heading() {
  return (
    <Rise className="mx-auto max-w-[42rem] px-[7vw] text-center">
      <p className="dept-label">The Instruments</p>
      <h2
        className="mt-2 text-balance font-display font-semibold"
        style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}
      >
        Every figure, engraved and accountable.
      </h2>
      <p className="mt-3 text-pretty text-[1.02rem] text-muted-foreground">
        Not another dashboard of charts you ignore. Each tool is a working
        instrument — it does one thing, shows its reasoning, and never moves
        real money without your stamp.
      </p>
    </Rise>
  );
}

/** Desktop: a pinned section where vertical scroll drives the plates sideways.
 *  The heading rides INSIDE the pinned viewport, directly above the strip, so
 *  the label and the first plates are read together — no dead band between the
 *  title and the cards. */
function Filmstrip() {
  const ref = useRef<HTMLDivElement>(null);
  const rowRef = useRef<HTMLDivElement>(null);
  const [dist, setDist] = useState(0);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });
  const x = useTransform(scrollYProgress, [0, 1], [0, -dist]);

  useEffect(() => {
    const measure = () => {
      const row = rowRef.current;
      if (!row) return;
      setDist(Math.max(0, row.scrollWidth - window.innerWidth + 40));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  return (
    <div ref={ref} className="full-bleed" style={{ height: `calc(100vh + ${dist}px)` }}>
      <div className="sticky top-0 flex h-screen flex-col justify-center gap-[4vh] overflow-hidden">
        <EngravedHeading />
        {/* the case — a perspective stage the plates are seated in at depth.
            Static depth (per-plate translateZ + reflections); no camera motion. */}
        <div className="iv-stage3d">
          <motion.div
            ref={rowRef}
            className="iv-deck flex items-end gap-7 px-[7vw]"
            style={{ x }}
          >
            {FEATURES.map((f, i) => (
              <FilmPlate key={f.no} f={f} index={i} />
            ))}
          </motion.div>
        </div>
      </div>
    </div>
  );
}

/** One grid plate (mobile / reduced-motion): plays its scene flourish as it
 *  scrolls into view — the only way the scenes animate without a hover. */
function GridPlate({ f, index }: { f: Feature; index: number }) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  useScrubVar(ref, "y", !reduce);
  return (
    <Rise delay={(index % 2) * 0.07}>
      <article
        ref={ref}
        className={cn("plate relative h-full bg-card p-5", !reduce && "iv-scrub")}
      >
        <PlateContent f={f} index={index} />
      </article>
    </Rise>
  );
}

/** Mobile / reduced-motion fallback: the plates as a plain vertical grid. */
function Grid() {
  return (
    <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
      {FEATURES.map((f, i) => (
        <GridPlate key={f.no} f={f} index={i} />
      ))}
    </div>
  );
}

/** The instruments — six feature plates as a living filmstrip on desktop. */
export function Instruments() {
  const reduce = useReducedMotion();
  const [wide, setWide] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setWide(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  const horizontal = wide && !reduce;

  // Horizontal: the heading travels inside the pinned strip (no gap). Grid:
  // the heading sits above the plates as usual.
  if (horizontal) {
    return (
      <section id="features" className="mt-2">
        <Filmstrip />
      </section>
    );
  }

  return (
    <section id="features" className="mt-12">
      <Heading />
      <Grid />
    </section>
  );
}
