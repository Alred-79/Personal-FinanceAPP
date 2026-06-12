import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * Letterpress buttons: type set in smallcaps that presses INTO the paper on
 * click (inset shadow), and lifts faintly off it on hover.
 */
const buttonVariants = cva(
  "press inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-none font-sans text-xs font-semibold uppercase tracking-[0.18em] transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "border border-rule-strong/70 bg-primary text-primary-foreground shadow-plate hover:-translate-y-px hover:shadow-plate-lg",
        destructive:
          "border border-rule-strong/70 bg-destructive text-destructive-foreground shadow-plate hover:-translate-y-px hover:shadow-plate-lg",
        outline:
          "border border-rule-strong/60 bg-card text-foreground shadow-plate hover:-translate-y-px hover:bg-wash hover:shadow-plate-lg",
        secondary:
          "border border-rule-strong/50 bg-secondary text-secondary-foreground shadow-plate hover:-translate-y-px hover:shadow-plate-lg",
        gold:
          "border border-rule-strong/70 bg-gold text-accent-foreground shadow-plate hover:-translate-y-px hover:shadow-plate-lg",
        ghost:
          "border border-transparent hover:border-rule hover:bg-wash",
        link: "normal-case font-medium tracking-normal text-primary underline-offset-4 hover:underline dark:text-accent",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 px-3 text-[11px]",
        lg: "h-11 px-8 text-sm",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
