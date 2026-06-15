import * as React from "react"

import { cn } from "@/lib/utils"

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
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
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

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent }
