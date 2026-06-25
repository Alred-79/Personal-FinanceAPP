import { useEffect, useRef, useState } from "react";
import { motion, useScroll, useTransform } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { useTilt } from "../hooks/useTilt";
import { FEATURES, type Feature } from "../data";
import { Rise } from "../shared";
import { PlateVisual } from "./instrumentVisuals";

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
 *  lifts off the page and comes alive on hover. Staggered up/down. */
function FilmPlate({ f, index }: { f: Feature; index: number }) {
  const lift = index % 2 === 0 ? -24 : 24;
  const { ref, enabled, handlers } = useTilt(9);
  return (
    <div className="shrink-0" style={{ transform: `translateY(${lift}px)` }}>
      <div ref={ref} className="iv-tilt w-[clamp(300px,26vw,372px)]" {...handlers}>
        <article className="iv-tilt__inner plate relative bg-card p-5">
          {enabled && <span aria-hidden className="iv-sheen" />}
          <PlateContent f={f} index={index} />
        </article>
      </div>
    </div>
  );
}

/** Desktop: a pinned section where vertical scroll drives the plates sideways. */
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
    <div ref={ref} className="full-bleed mt-12" style={{ height: `calc(100vh + ${dist}px)` }}>
      <div className="sticky top-0 flex h-screen items-center overflow-hidden">
        <motion.div ref={rowRef} className="flex items-center gap-7 px-[7vw]" style={{ x }}>
          {FEATURES.map((f, i) => (
            <FilmPlate key={f.no} f={f} index={i} />
          ))}
        </motion.div>
      </div>
    </div>
  );
}

/** Mobile / reduced-motion fallback: the plates as a plain vertical grid. */
function Grid() {
  return (
    <div className="mt-10 grid grid-cols-1 gap-4 sm:grid-cols-2">
      {FEATURES.map((f, i) => (
        <Rise key={f.no} delay={(i % 2) * 0.07}>
          <article className="plate relative h-full bg-card p-5">
            <PlateContent f={f} index={i} />
          </article>
        </Rise>
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

  return (
    <section id="features" className="mt-28">
      <Rise className="mx-auto max-w-[42rem] text-center">
        <p className="dept-label">The Instruments</p>
        <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
          Every figure, engraved and accountable.
        </h2>
        <p className="mt-3 text-[1.02rem] text-muted-foreground">
          Not another dashboard of charts you ignore. Each tool is a working
          instrument — it does one thing, shows its reasoning, and never moves
          real money without your stamp.
        </p>
      </Rise>
      {horizontal ? <Filmstrip /> : <Grid />}
    </section>
  );
}
