import { forwardRef, ReactNode } from "react";
import { motion, useMotionValue, useSpring, useMotionTemplate } from "motion/react";
import { cn } from "@/lib/utils";
import { useReducedMotion, usePointerFine } from "@/hooks/useEnvironment";
import { CornerRosette } from "./Guilloche";

type CertificateProps = React.HTMLAttributes<HTMLDivElement> & {
  children: ReactNode;
  /** Seed so each certificate's corner engraving differs but stays stable. */
  seed?: number;
  /** Accent rule colour, e.g. a category tint. */
  accent?: string;
  /**
   * frontend-elevation: opt in to the "alive" plate — on hover it lifts (spring),
   * tilts in 3D toward the cursor, and a gold sheen tracks the pointer. Falls back
   * to the plain static plate under reduced motion or on a coarse pointer.
   */
  alive?: boolean;
  /** max tilt in degrees (default 7) */
  maxTilt?: number;
};

/** The certificate's framing: accent rule + corner rosettes + content. */
function CertificateFrame({
  children,
  seed,
  accent,
}: {
  children: ReactNode;
  seed: number;
  accent?: string;
}) {
  return (
    <>
      {/* accent rule */}
      {accent && (
        <div className="absolute inset-x-0 top-0 z-[2] h-[3px]" style={{ background: accent }} />
      )}
      {/* corner rosettes */}
      <div className="pointer-events-none absolute -left-4 -top-4 z-[2] text-gold/20">
        <CornerRosette size={64} seed={seed} />
      </div>
      <div className="pointer-events-none absolute -bottom-5 -right-5 z-[2] text-gold/15">
        <CornerRosette size={80} seed={seed + 100} />
      </div>
      <div className="relative z-[2]">{children}</div>
    </>
  );
}

/**
 * A share-certificate plate: heavy double frame, an engraved rosette tucked
 * into each corner, and a fine accent rule along the top. Used for budget
 * envelopes and savings goals.
 */
export const Certificate = forwardRef<HTMLDivElement, CertificateProps>(function Certificate(
  { children, seed = 1, accent, className, onClick, alive = false, maxTilt = 7, ...rest },
  ref
) {
  const reduce = useReducedMotion();
  const fine = usePointerFine();
  const rx = useSpring(useMotionValue(0), { stiffness: 150, damping: 15 });
  const ry = useSpring(useMotionValue(0), { stiffness: 150, damping: 15 });
  const mx = useMotionValue(50);
  const my = useMotionValue(50);
  const sheen = useMotionTemplate`radial-gradient(340px circle at ${mx}% ${my}%, hsl(var(--gold) / 0.16), transparent 60%)`;

  // `rest` carries any props injected by a Radix `Slot` trigger (data-state,
  // aria-*, id, onPointerDown…); spreading it onto the root keeps the plate a
  // correct, accessible trigger. `ref` is forwarded for the same reason.
  const frame = (
    <CertificateFrame seed={seed} accent={accent}>
      {children}
    </CertificateFrame>
  );

  // Static plate — original behaviour (and the alive fallback).
  if (!alive || reduce || !fine) {
    return (
      <div
        ref={ref}
        onClick={onClick}
        className={cn(
          "plate group relative overflow-hidden bg-card transition-transform duration-300",
          onClick && "cursor-pointer hover:-translate-y-0.5",
          className
        )}
        {...rest}
      >
        {frame}
      </div>
    );
  }

  // Alive plate — spring lift + 3D tilt + cursor-tracking gold sheen.
  return (
    <motion.div
      ref={ref}
      onClick={onClick}
      className={cn(
        "plate group relative overflow-hidden bg-card",
        onClick && "cursor-pointer",
        className
      )}
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width;
        const py = (e.clientY - r.top) / r.height;
        ry.set((px - 0.5) * maxTilt);
        rx.set((0.5 - py) * maxTilt);
        mx.set(px * 100);
        my.set(py * 100);
      }}
      onPointerLeave={() => {
        rx.set(0);
        ry.set(0);
      }}
      whileHover={{ y: -6, scale: 1.02, boxShadow: "0 24px 60px hsl(222 40% 4% / 0.22)" }}
      transition={{ type: "spring", stiffness: 300, damping: 22 }}
      style={{ rotateX: rx, rotateY: ry, transformPerspective: 1000, transformStyle: "preserve-3d" }}
      {...(rest as React.ComponentProps<typeof motion.div>)}
    >
      <motion.div
        aria-hidden
        style={{ position: "absolute", inset: 0, background: sheen, pointerEvents: "none", zIndex: 1 }}
      />
      {frame}
    </motion.div>
  );
});
Certificate.displayName = "Certificate";
