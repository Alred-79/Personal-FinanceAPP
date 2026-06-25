import { Rise } from "../shared";
import { LiveForecast } from "./forecast/LiveForecast";
import { HowItThinks } from "./forecast/HowItThinks";
import { Vignettes } from "./forecast/Vignettes";

/**
 * The Forecast — the product's flagship. The landing portrays the real engine
 * honestly: a calibrated probabilistic projection (moving-block bootstrap +
 * conformal band + change-point detection), a live what-if, and the supporting
 * surfaces (Safe-to-Spend, Compare, calendar). See server/src/services/forecast_*.
 */
export function Forecast() {
  return (
    <section id="forecast" className="mt-28">
      <Rise className="mx-auto max-w-[44rem] text-center">
        <p className="dept-label">The Sea-Chart · live</p>
        <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
          A forecast that knows what it doesn't know.
        </h2>
        <p className="mt-3 text-[1.02rem] text-muted-foreground">
          Not a flat line — a calibrated probability. Drag to model heavier or lighter
          spending and watch hundreds of simulated futures, the ~90% trough band, and your
          overdraft odds re-sound. Then stress-test any decision before you make it.
        </p>
      </Rise>

      <Rise className="mx-auto mt-8 max-w-[760px]" delay={0.1}>
        <LiveForecast />
      </Rise>

      <HowItThinks />

      <div className="mt-16">
        <Rise className="text-center">
          <p className="dept-label">The whole instrument</p>
          <h3 className="mt-1.5 font-display font-semibold" style={{ fontSize: "clamp(1.3rem,3vw,1.9rem)" }}>
            One number, and all the work behind it.
          </h3>
        </Rise>
        <Vignettes />
      </div>
    </section>
  );
}
