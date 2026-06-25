import { useEffect, useRef, useState } from "react";
import { motion, useScroll, useTransform } from "motion/react";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { FEATURES, type Feature } from "../data";
import { FeatureIcon, Rise } from "../shared";

/** A small engraved motif unique to each instrument, drawn under the copy. */
function PlateMotif({ index }: { index: number }) {
  const s = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  const motifs = [
    <path key="0" d="M1 12c8-11 15 9 23 0s15-9 23 0" {...s} />, // sea-chart wave
    <g key="1" {...s}>
      <path d="M2 7h40" />
      <path d="M2 13h28" strokeDasharray="3 3" />
      <path d="M2 19h34" />
    </g>, // clerk diff
    <g key="2" {...s}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 6v12M14.4 9.2A2 2 0 0 0 10 10.6c0 2 4 2 4 4a2 2 0 0 1-4 .6" />
    </g>, // minted coin
    <g key="3" {...s}>
      <path d="M2 6h44M2 12h44M2 18h26" />
    </g>, // import rows
    <g key="4" {...s}>
      <path d="M12 2 4 5v6c0 5 8 8 8 8s8-3 8-8V5Z" />
      <path d="m9 11 2 2 4-4" />
    </g>, // auditor shield
    <g key="5" {...s}>
      <rect x="3" y="3" width="18" height="18" rx="1" />
      <path d="m7 12 3 3 6-6" />
    </g>, // tax stamp
  ];
  return (
    <svg width="100%" height="26" viewBox="0 0 48 24" preserveAspectRatio="xMinYMid meet" className="text-gold/55">
      {motifs[index % motifs.length]}
    </svg>
  );
}

/** Shared plate content — big number watermark, glyph, title, body, motif. */
function PlateBody({ f, index }: { f: Feature; index: number }) {
  return (
    <>
      <span
        aria-hidden
        className="pointer-events-none absolute -right-1 -top-7 select-none font-display text-[7rem] font-semibold leading-none text-rule-strong/[0.07]"
      >
        {f.no.replace(/\D/g, "")}
      </span>
      <FeatureIcon>{f.icon}</FeatureIcon>
      <h3 className="font-display text-[1.28rem] font-semibold">{f.title}</h3>
      <p className="mt-2 text-[0.92rem] leading-relaxed text-muted-foreground">{f.body}</p>
      <div className="mt-5 border-t border-rule-strong/25 pt-3">
        <PlateMotif index={index} />
      </div>
    </>
  );
}

/** One filmstrip plate — staggered up/down, lifts on hover. */
function FilmPlate({ f, index }: { f: Feature; index: number }) {
  const lift = index % 2 === 0 ? -24 : 24; // alternating vertical stagger
  return (
    <div className="shrink-0" style={{ transform: `translateY(${lift}px)` }}>
      <article className="plate relative w-[clamp(290px,25vw,360px)] overflow-hidden bg-card p-6 transition-[transform,box-shadow] duration-300 hover:-translate-y-1.5 hover:shadow-plate-lg">
        <PlateBody f={f} index={index} />
      </article>
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
          <article className="plate relative h-full overflow-hidden bg-card p-6">
            <PlateBody f={f} index={i} />
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
