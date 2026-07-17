export default function RouteFallback() {
  return (
    <div className="grid min-h-screen place-items-center bg-background text-foreground">
      <div className="text-center">
        <span
          className="mx-auto grid h-11 w-11 place-items-center border border-rule-strong/50 font-display text-xl text-gold"
          aria-hidden
        >
          £
        </span>
        <p className="mt-3 font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
          Opening the ledger
        </p>
      </div>
    </div>
  );
}
