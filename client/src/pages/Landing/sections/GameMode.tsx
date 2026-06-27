import { useState } from "react";
import { Rise } from "../shared";
import { GAMES, type ArcadeGame } from "./game/arcadeData";
import { DebtBoss } from "./game/DebtBoss";
import { SubscriptionWatch } from "./game/SubscriptionWatch";

/**
 * The Penny Arcade — the product's game layer made literal, but insight-first:
 * each "amusement" is a REAL in-app mechanic you can play with, chosen to show
 * the value rather than assert it. The Debt Boss is a payoff simulator on the
 * real seeded debt (watch minimum payments feed interest); Subscription Watch
 * is the real recurring-charge detector (price-creep + unused flags). Every
 * figure is a real product mechanic, never a points gimmick — and the section
 * leads with what each one teaches you, then states the two honest rules.
 */
export function GameMode() {
  const [game, setGame] = useState<ArcadeGame>("boss");

  return (
    <section id="game" className="mt-28">
      <Rise className="mx-auto max-w-[44rem] text-center">
        <p className="dept-label">The game, with a point</p>
        <h2 className="mt-2 font-display font-semibold" style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}>
          A game that shows you what your money is doing.
        </h2>
        <p className="mt-3 text-[1.02rem] text-muted-foreground">
          Each one is a real product mechanic you can play with. See what minimum payments
          actually cost you in interest, and watch the app surface the subscriptions quietly
          draining you. Nothing here is a points gimmick, and nothing rewards spending.
        </p>
      </Rise>

      <Rise delay={0.08}>
        <div className="arc-cabinet">
          {/* marquee */}
          <div className="arc-marquee">
            <span className="arc-marquee__lamp" aria-hidden />
            <span className="arc-marquee__title">THE&nbsp;PENNY&nbsp;ARCADE</span>
            <span className="arc-marquee__coin" aria-hidden>¢</span>
          </div>

          {/* screen — the active demo (remounts on switch to reset) */}
          <div className="arc-screen">
            {game === "boss" ? <DebtBoss key="boss" /> : <SubscriptionWatch key="watch" />}
          </div>

          {/* control deck — pick your demo */}
          <div className="arc-deck" role="tablist" aria-label="Choose a demo">
            {GAMES.map((g) => (
              <button
                key={g.id}
                type="button"
                role="tab"
                aria-selected={game === g.id}
                className="arc-select"
                onClick={() => setGame(g.id)}
              >
                <span className="arc-select__no" aria-hidden>{g.no}</span>
                <span className="arc-select__body">
                  <span className="arc-select__title">{g.title}</span>
                  <span className="arc-select__blurb">{g.blurb}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </Rise>

      {/* The honest rules of the game — why this isn't the spend-to-win gimmick
          (docs/FRONTEND-REPOSITIONING §5): XP rewards seeing & doing, never spending. */}
      <div className="mt-8 grid gap-3 sm:grid-cols-2">
        {GAME_RULES.map((rule, i) => (
          <Rise key={rule.title} delay={i * 0.06}>
            <article className="plate h-full bg-card p-5">
              <p className="dept-label text-gold">{rule.kicker}</p>
              <h3 className="mt-1.5 font-display text-[1.08rem] font-semibold leading-snug">
                {rule.title}
              </h3>
              <p className="mt-2 text-[0.9rem] leading-relaxed text-muted-foreground">
                {rule.body}
              </p>
            </article>
          </Rise>
        ))}
      </div>
    </section>
  );
}

/** The two promises that separate this from gamified-finance gimmicks. */
const GAME_RULES = [
  {
    kicker: "The one rule",
    title: "XP for real money wins — never for spending.",
    body: "You level up by paying a bill on time, funding a goal, closing a day under budget. Spending earns you nothing. There's no store, no way to buy your way up — the only currency is real progress.",
  },
  {
    kicker: "No streak shame",
    title: "A missed day won't break you.",
    body: "Life happens. Miss a day and you don't lose your progress or get guilt-tripped into a doom-streak — grays, wards, and grace keep the game forgiving on purpose. It's here to keep you going, not to punish you.",
  },
];
