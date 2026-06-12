import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/** Category chips set like inventory tags: fine rule, mono smallcaps. */
const badgeVariants = cva(
  "inline-flex items-center rounded-none border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.14em] transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background",
  {
    variants: {
      variant: {
        default: "border-rule-strong/60 bg-primary text-primary-foreground",
        secondary: "border-rule-strong/40 bg-secondary text-secondary-foreground",
        destructive: "border-debit/60 bg-transparent text-debit",
        outline: "border-rule-strong/50 bg-transparent text-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
