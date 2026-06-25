import { useEffect, useRef, useState, type RefObject } from "react";
import { motion, useScroll, useTransform } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { useTilt } from "../hooks/useTilt";
import { FEATURES, type Feature } from "../data";
import { Rise } from "../shared";
import { PlateVisual } from "./instrumentVisuals";

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
    </>
  );
}

/** One filmstrip plate — a cursor-tracking 3D tilt card whose specimen scene
 *  lifts off the page and comes alive on hover, and also plays its flourish once
 *  as it scrolls through the centre of the strip. Staggered up/down. */
function FilmPlate({ f, index }: { f: Feature; index: number }) {
  const lift = index % 2 === 0 ? -24 : 24;
  const { ref, enabled, handlers } = useTilt(9);
  // The filmstrip only mounts for non-reduced-motion. Scrub the scene to the
  // plate's leftward travel across the strip — it unfolds at the scroll's pace.
  const wrapRef = useRef<HTMLDivElement>(null);
  useScrubVar(wrapRef, "x");
  return (
    <div ref={wrapRef} className="iv-scrub shrink-0" style={{ transform: `translateY(${lift}px)` }}>
      <div ref={ref} className="iv-tilt w-[clamp(300px,26vw,372px)]" {...handlers}>
        <article className="iv-tilt__inner plate relative bg-card p-5">
          {enabled && <span aria-hidden className="iv-sheen" />}
          <PlateContent f={f} index={index} />
        </article>
      </div>
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
      <div className="sticky top-0 flex h-screen flex-col justify-center gap-10 overflow-hidden">
        <Heading />
        <motion.div ref={rowRef} className="flex items-center gap-7 px-[7vw]" style={{ x }}>
          {FEATURES.map((f, i) => (
            <FilmPlate key={f.no} f={f} index={i} />
          ))}
        </motion.div>
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
      <section id="features" className="mt-28">
        <Filmstrip />
      </section>
    );
  }

  return (
    <section id="features" className="mt-28">
      <Heading />
      <Grid />
    </section>
  );
}
