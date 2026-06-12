/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./client/index.html", "./client/src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar))",
          foreground: "hsl(var(--sidebar-foreground))",
        },
        chart: {
          1: "hsl(var(--chart-1))",
          2: "hsl(var(--chart-2))",
          3: "hsl(var(--chart-3))",
          4: "hsl(var(--chart-4))",
          5: "hsl(var(--chart-5))",
          6: "hsl(var(--chart-6))",
        },
        /* Engraver's extras */
        gold: {
          DEFAULT: "hsl(var(--gold))",
          soft: "hsl(var(--gold-soft))",
        },
        rule: {
          DEFAULT: "hsl(var(--rule))",
          strong: "hsl(var(--rule-strong))",
        },
        debit: "hsl(var(--debit))",
        credit: "hsl(var(--credit))",
        wash: "hsl(var(--ink-wash))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      boxShadow: {
        /* Engraved plate shadows. The old `brutal` names are kept so any
           component not yet redesigned still lands in the new language. */
        plate:
          "0 1px 0 hsl(var(--paper-high)) inset, 0 2px 10px hsl(167 30% 12% / 0.07)",
        "plate-lg":
          "0 1px 0 hsl(var(--paper-high)) inset, 0 10px 30px hsl(167 30% 12% / 0.12)",
        brutal:
          "0 1px 0 hsl(var(--paper-high)) inset, 0 2px 10px hsl(167 30% 12% / 0.08)",
        "brutal-sm":
          "0 1px 0 hsl(var(--paper-high)) inset, 0 1px 5px hsl(167 30% 12% / 0.07)",
        "brutal-lg":
          "0 1px 0 hsl(var(--paper-high)) inset, 0 10px 30px hsl(167 30% 12% / 0.12)",
        card:
          "0 1px 0 hsl(var(--paper-high)) inset, 0 2px 10px hsl(167 30% 12% / 0.07)",
        "card-dark":
          "0 1px 0 hsl(44 36% 87% / 0.04) inset, 0 2px 14px hsl(168 40% 2% / 0.5)",
        letterpress: "inset 0 2px 4px hsl(167 30% 12% / 0.25)",
      },
      fontFamily: {
        sans: ["'Instrument Sans'", "'Helvetica Neue'", "system-ui", "sans-serif"],
        display: ["Fraunces", "Georgia", "serif"],
        mono: ["'Spline Sans Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      letterSpacing: {
        engraved: "0.32em",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "terminal-blink": {
          "0%, 100%": { opacity: "0" },
          "50%": { opacity: "1" },
        },
        "count-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "rise-in": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "terminal-blink": "terminal-blink 1s step-end infinite",
        "count-up": "count-up 0.4s ease-out both",
        "rise-in": "rise-in 0.5s cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
