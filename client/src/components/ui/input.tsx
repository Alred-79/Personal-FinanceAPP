import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Ledger entry fields: a quiet full hairline with an emphatic baseline rule —
 * focusing draws a firm ink line under the entry, like ruling a ledger.
 */
const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-11 w-full rounded-none border border-rule bg-transparent px-3 py-1 font-sans text-base text-foreground transition-[box-shadow,border-color] duration-200 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:italic placeholder:text-muted-foreground/70 focus-visible:border-rule-strong focus-visible:outline-none focus-visible:shadow-[inset_0_-2px_0_hsl(var(--ring))] disabled:cursor-not-allowed disabled:opacity-50 md:text-sm",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
