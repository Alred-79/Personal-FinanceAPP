import { STEPS } from "../data";
import { Rise } from "../shared";

/** How it works — four ledger rows, "entries to open", each with a glyph. */
export function HowItWorks() {
  return (
    <section id="how" className="mt-28">
      <Rise>
        <p className="section-rule mx-auto max-w-[1080px] text-[0.7rem] uppercase tracking-[0.28em] text-muted-foreground">
          Four entries to open
        </p>
      </Rise>
      <div className="mt-8 border-t border-rule-strong/40">
        {STEPS.map((s, i) => (
          <Rise key={s.idx} delay={i * 0.06}>
            <div className="ledger-row group grid grid-cols-[auto_1fr_auto] items-center gap-5 border-b border-rule px-1 py-6 sm:gap-6">
              <div className="w-8 font-display text-[1.6rem] text-gold sm:w-10 sm:text-[1.8rem]">
                {s.idx}
              </div>
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="grid h-8 w-8 shrink-0 place-items-center border border-rule-strong/50 text-gold">
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                      {s.icon}
                    </svg>
                  </span>
                  <h3 className="font-display text-[1.12rem] font-semibold sm:text-[1.18rem]">
                    {s.title}
                  </h3>
                </div>
                <p className="mt-1.5 text-[0.92rem] leading-relaxed text-muted-foreground">
                  {s.body}
                </p>
              </div>
              <span className="manicule text-[1.1rem]">☞</span>
            </div>
          </Rise>
        ))}
      </div>
    </section>
  );
}
