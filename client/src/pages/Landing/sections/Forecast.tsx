import { Rise } from "../shared";
import { LiveForecast } from "./forecast/LiveForecast";
import { HowItThinks } from "./forecast/HowItThinks";
import { Vignettes } from "./forecast/Vignettes";

/**
 * The Forecast — how the safe-to-spend number is made and how a decision moves
 * it. The landing portrays the real engine honestly: scheduled cash flows plus a
 * history-dependent simulation when the data supports one, an illustrative live
 * what-if, and the supporting surfaces (Safe-to-Spend, Compare, calendar). See
 * server/src/services/forecast_*.
 */
export function Forecast() {
  return (
    <section id="forecast" className="mt-24">
      <Rise className="mx-auto max-w-[44rem] text-center">
        <p className="dept-label">How the number is made</p>
        <h2 className="mt-2 text-balance font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
          Test a purchase before you make it.
        </h2>
        <p className="mt-3 text-pretty text-[1.02rem] text-muted-foreground">
          The Ledger lays out every scheduled bill and paycheck for the next 30 days.
          When there is enough varied history, it adds a modeled range for everyday
          spending; otherwise it sticks to the schedule. Drag this sample chart or
          add a what-if to see how one decision changes the month.
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
