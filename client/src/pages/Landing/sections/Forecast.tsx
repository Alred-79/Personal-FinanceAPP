import { Rise } from "../shared";
import { LiveForecast } from "./forecast/LiveForecast";
import { HowItThinks } from "./forecast/HowItThinks";
import { Vignettes } from "./forecast/Vignettes";

/**
 * The Forecast — the product's flagship. The landing portrays the real engine
 * honestly: scheduled cash flows plus a history-dependent simulation when the
 * data supports one, an illustrative live what-if, and the supporting
 * surfaces (Safe-to-Spend, Compare, calendar). See server/src/services/forecast_*.
 */
export function Forecast() {
  return (
    <section id="forecast" className="mt-28">
      <Rise className="mx-auto max-w-[44rem] text-center">
        <p className="dept-label">The 30-day outlook · uncertainty included</p>
        <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
          See the range before you make the move.
        </h2>
        <p className="mt-3 text-[1.02rem] text-muted-foreground">
          A bank balance cannot account for everything already spoken for. The Ledger
          starts with scheduled cash flow. When there is enough varied history, it adds
          modeled spending paths and labels the range; otherwise it stays schedule-only.
          Drag this sample chart or add a what-if to see how the illustration changes.
        </p>
      </Rise>

      <Rise className="mx-auto mt-8 max-w-[760px]" delay={0.1}>
        <p className="mb-2 text-center font-sans text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Interactive illustration · sample data
        </p>
        <LiveForecast />
      </Rise>

      <HowItThinks />

      <div className="mt-16">
        <Rise className="text-center">
          <p className="dept-label">The whole answer</p>
          <h3 className="mt-1.5 font-display font-semibold" style={{ fontSize: "clamp(1.3rem,3vw,1.9rem)" }}>
            One number, with the work close enough to inspect.
          </h3>
        </Rise>
        <Vignettes />
      </div>
    </section>
  );
}
