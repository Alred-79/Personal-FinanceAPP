import * as React from "react"
import { motion, useMotionValue, useSpring, useMotionTemplate } from "motion/react"

import { cn } from "@/lib/utils"
import { useReducedMotion, usePointerFine } from "@/hooks/useEnvironment"

/**
 * Cards are engraved plates: a heavy outer rule with a hairline inner frame
 * (the `plate` class), sitting on the paper with a faint lift.
 *
 * frontend-elevation: pass `raking` to opt in to the cursor "desk-lamp"
 * highlight (a soft glow that follows the pointer for engraved depth). It's
 * opt-in so existing cards are untouched; the highlight only shows on real
 * hover (CSS-gated) and is dropped under reduced motion.
 */
type CardProps = React.HTMLAttributes<HTMLDivElement> & { raking?: boolean }

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, raking, onPointerMove, ...props }, ref) => {
    const handlePointerMove = raking
      ? (e: React.PointerEvent<HTMLDivElement>) => {
          const el = e.currentTarget
          const r = el.getBoundingClientRect()
          el.style.setProperty("--mx", `${((e.clientX - r.left) / r.width) * 100}%`)
          el.style.setProperty("--my", `${((e.clientY - r.top) / r.height) * 100}%`)
          onPointerMove?.(e)
        }
      : onPointerMove
    return (
      <div
        ref={ref}
        className={cn(
          "plate rounded-none text-card-foreground",
          raking && "plate-raking",
          className
        )}
        onPointerMove={handlePointerMove}
        {...props}
      />
    )
  }
)
Card.displayName = "Card"

/**
 * TiltCard — a plate that comes alive: on hover it LIFTS (spring), tilts in 3D
 * toward the cursor, and a gold sheen tracks the pointer (frontend-elevation
 * "powered" look). Opt-in, separate from the plain Card so existing usages are
 * untouched. Falls back to a plain static plate under reduced motion or on touch.
 *
 * `onHoverChange` lets a parent react (e.g. tint a reactive background) when the
 * card is entered/left.
 */
type TiltCardProps = React.HTMLAttributes<HTMLDivElement> & {
  /** max tilt in degrees (default 8) */
  maxTilt?: number
  /** fired true on pointer-enter, false on leave */
  onHoverChange?: (hovered: boolean) => void
}

const TiltCard = React.forwardRef<HTMLDivElement, TiltCardProps>(
  ({ className, children, maxTilt = 8, onHoverChange, ...props }, ref) => {
    const reduce = useReducedMotion()
    const fine = usePointerFine()
    const rx = useSpring(useMotionValue(0), { stiffness: 150, damping: 15 })
    const ry = useSpring(useMotionValue(0), { stiffness: 150, damping: 15 })
    const mx = useMotionValue(50)
    const my = useMotionValue(50)
    const sheen = useMotionTemplate`radial-gradient(340px circle at ${mx}% ${my}%, hsl(var(--gold) / 0.16), transparent 60%)`

    // No tilt where it shouldn't run — render a plain plate.
    if (reduce || !fine) {
      return (
        <div ref={ref} className={cn("plate rounded-none text-card-foreground", className)} {...props}>
          {children}
        </div>
      )
    }

    return (
      <motion.div
        ref={ref}
        className={cn("plate rounded-none text-card-foreground", className)}
        onPointerMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const px = (e.clientX - r.left) / r.width
          const py = (e.clientY - r.top) / r.height
          ry.set((px - 0.5) * maxTilt)
          rx.set((0.5 - py) * maxTilt)
          mx.set(px * 100)
          my.set(py * 100)
        }}
        onPointerEnter={() => onHoverChange?.(true)}
        onPointerLeave={() => {
          rx.set(0)
          ry.set(0)
          onHoverChange?.(false)
        }}
        whileHover={{ y: -6, scale: 1.02, boxShadow: "0 24px 60px hsl(222 40% 4% / 0.22)" }}
        transition={{ type: "spring", stiffness: 300, damping: 22 }}
        style={{ position: "relative", rotateX: rx, rotateY: ry, transformPerspective: 1000, transformStyle: "preserve-3d" }}
        {...(props as React.ComponentProps<typeof motion.div>)}
      >
        <motion.div
          aria-hidden
          style={{ position: "absolute", inset: 0, background: sheen, pointerEvents: "none", zIndex: 1 }}
        />
        <div style={{ position: "relative", zIndex: 2 }}>{children}</div>
      </motion.div>
    )
  }
)
TiltCard.displayName = "TiltCard"

const CardHeader = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex flex-col space-y-1.5 p-6", className)}
    {...props}
  />
))
CardHeader.displayName = "CardHeader"

const CardTitle = React.forwardRef<
  HTMLHeadingElement,
  React.HTMLAttributes<HTMLHeadingElement>
>(({ className, ...props }, ref) => (
  <h2
    ref={ref}
    className={cn(
      "font-sans text-[11px] font-semibold uppercase leading-none tracking-[0.28em] text-muted-foreground",
      className
    )}
    {...props}
  />
))
CardTitle.displayName = "CardTitle"

const CardDescription = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("text-sm text-muted-foreground", className)}
    {...props}
  />
))
CardDescription.displayName = "CardDescription"

const CardContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div ref={ref} className={cn("p-6 pt-0", className)} {...props} />
))
CardContent.displayName = "CardContent"

const CardFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn("flex items-center p-6 pt-0", className)}
    {...props}
  />
))
CardFooter.displayName = "CardFooter"

export { Card, TiltCard, CardHeader, CardFooter, CardTitle, CardDescription, CardContent }
