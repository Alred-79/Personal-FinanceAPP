import { useCallback, useRef, useState } from "react";
import { motion } from "motion/react";
import { Guilloche, GuillocheBand } from "@/components/engraving/Guilloche";
import { useReducedMotion } from "@/hooks/useEnvironment";
import { cn } from "@/lib/utils";
import { EASE, Rise } from "../shared";
import { SpecimenNote } from "./specimen/SpecimenNote";
import { TierRegister } from "./specimen/TierRegister";
import { Cite } from "./specimen/Cite";
import {
  IMPACT,
  NOT_CLAIMED,
  PLATES,
  TIERS,
  markerStyle,
  type PlateN,
} from "./specimen/specimenData";

/**
 * THE SPECIMEN SHEET
 *
 * The page's third and last register on security, and deliberately the deepest.
 * The Vault says what the product promises you. The Reading Room shows what
 * happens to one request. This sheet is the technical annex: how the agent
 * surface is built, and exactly where to look to check.
 *
 * The form is the argument twice over. First, currency documents its own
 * anti-counterfeiting features as numbered callouts pointing at a specimen
 * note, and these controls ARE anti-forgery features. Second — and this is what
 * lets the sheet be complete rather than flattering — currency grades those
 * features by the instrument you verify them with: Level 1 in the hand, Level 2
 * under a lamp, Level 3 in a laboratory. Borrowing that grading turns the
 * awkward part into the designed part. A mechanism that needs Postgres and an
 * opt-in setting, or one that is built and tested but ships behind a
 * default-off flag, appears here at its own level with its precondition printed
 * as the first line of the entry, instead of being padded in among the
 * unconditional ones or left out to keep the story clean.
 *
 * What no level can absorb stays stated outright at the foot: there is no PII
 * redaction on the agent path, and no flag that adds one.
 */
export function SpecimenSheet() {
  const reduce = useReducedMotion();
  const [active, setActive] = useState<PlateN>(1);
  /* Whether a visitor has actually put a feature under the lens. On load the
     specimen is whole and at full contrast — nothing is being inspected yet, so
     nothing should be out of focus. The first deliberate choice flips it, and
     from then on the plate recedes behind whichever callout is open. */
  const [inspecting, setInspecting] = useState(false);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  const plate = PLATES.find((p) => p.n === active) ?? PLATES[0];

  /* Roving tabindex, automatic activation: the panel is cheap to render, so a
     visitor arrowing along the callouts reads them without a second keypress. */
  const onKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const keys = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp", "Home", "End"];
    if (!keys.includes(e.key)) return;
    e.preventDefault();
    setInspecting(true);
    setActive((cur) => {
      const i = PLATES.findIndex((p) => p.n === cur);
      const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
      const next =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? PLATES.length - 1
            : (i + step + PLATES.length) % PLATES.length;
      tabs.current[next]?.focus();
      return PLATES[next].n;
    });
  }, []);

  return (
    <section id="specimen" className="spx mt-28">
      <Rise className="mx-auto max-w-[46rem] text-center">
        <p className="dept-label">The Specimen Sheet · Anti-forgery features</p>
        <h2
          className="mt-2 text-balance font-display font-semibold"
          style={{ fontSize: "clamp(1.8rem,4.5vw,2.8rem)" }}
        >
          Every note prints the reasons it can&rsquo;t be forged.
        </h2>
        <p className="mx-auto mt-3 max-w-[40rem] text-pretty text-[1.02rem] leading-relaxed text-muted-foreground">
          Intaglio, the thread, microprint, the failed impression — a banknote
          documents its own defences and invites you to check them. Here is the
          same sheet for the agent surface: every mechanism with the attack it
          exists to stop, the file and test that prove it, and the level at which
          you can verify it.
        </p>
        <p className="mx-auto mt-3 max-w-[36rem] text-[0.8rem] leading-relaxed text-muted-foreground/85">
          The Vault above states what the product promises you. The Reading Room
          shows what happens to a single request. This one is for the engineer who
          would rather open the files.
        </p>
      </Rise>

      {/* ── the engraved figure block: what the audit actually turned up ──── */}
      <Rise delay={0.05}>
        <div className="spx-figures" role="list">
          {IMPACT.map((f) => (
            <div className="spx-figure" role="listitem" key={f.caption}>
              <span className="spx-figure__value">{f.value}</span>
              <span className="spx-figure__caption">{f.caption}</span>
            </div>
          ))}
        </div>
      </Rise>

      <Rise delay={0.08}>
        <div className="spx-sheet mt-12">
          <div className="spx-sheet__band" aria-hidden>
            <GuillocheBand height={14} waves={5} seed={41} />
          </div>

          <p className="spx-sheet__caption">
            <span className="spx-sheet__level">Level I</span>
            the five strongest, callout by callout
          </p>

          {/* ── the plate: the engraved note, with its callouts pinned on ──
              `is-inspecting` takes the whole specimen out of focus behind the
              open reading, leaving only the selected leader and disc sharp. */}
          <div className={cn("spx-plate", inspecting && "is-inspecting")}>
            {/* the engraved field — the rosette sits inside the portrait vignette,
                so it is anchored to the note and not to the callout rail below */}
            <div className="spx-plate__field">
              <div className="spx-plate__rosette" aria-hidden>
                <Guilloche size={240} rings={6} seed={23} strokeWidth={0.5} animate className="h-auto w-full" />
              </div>
              <SpecimenNote active={active} />
            </div>

            <div
              className="spx-marks"
              role="tablist"
              aria-label="The five Level I callouts"
              onKeyDown={onKeyDown}
            >
              {PLATES.map((p, i) => (
                <button
                  key={p.n}
                  ref={(el) => {
                    tabs.current[i] = el;
                  }}
                  type="button"
                  role="tab"
                  id={`spx-tab-${p.n}`}
                  aria-selected={active === p.n}
                  aria-controls="spx-panel"
                  tabIndex={active === p.n ? 0 : -1}
                  onClick={() => {
                    setInspecting(true);
                    setActive(p.n);
                  }}
                  className={cn("spx-mark", active === p.n && "is-on")}
                  style={markerStyle(p.marker)}
                >
                  <span className="spx-mark__disc" aria-hidden>
                    {p.n}
                  </span>
                  <span className="spx-mark__name">{p.feature}</span>
                </button>
              ))}
            </div>
          </div>

          {/* ── the reading: what the selected callout actually is ───────── */}
          <div
            className="spx-reading"
            role="tabpanel"
            id="spx-panel"
            aria-labelledby={`spx-tab-${active}`}
            tabIndex={0}
          >
            <motion.div
              key={active}
              className="spx-reading__grid"
              initial={reduce ? false : { opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: reduce ? 0 : 0.5, ease: EASE }}
            >
              <div className="spx-reading__key">
                <span className="spx-reading__numeral" aria-hidden>
                  {plate.n}
                </span>
                <h3 className="spx-reading__feature">{plate.feature}</h3>
                <p className="spx-reading__mech">{plate.mechanism}</p>
                <p className="spx-reading__kind">{plate.kind}</p>
              </div>

              <div className="spx-reading__body">
                <div className="spx-entry spx-entry--threat">
                  <h4 className="spx-entry__label">The threat</h4>
                  <p className="spx-entry__text">{plate.threat}</p>
                </div>
                <div className="spx-entry">
                  <h4 className="spx-entry__label">The enforcement</h4>
                  <p className="spx-entry__text">{plate.enforcement}</p>
                </div>
                <div className="spx-proof">
                  <h4 className="spx-entry__label">The proof</h4>
                  <ul className="spx-proof__list">
                    {plate.proof.map((c) => (
                      <li key={`${c.path}${c.symbol ?? ""}`}>
                        <Cite {...c} />
                      </li>
                    ))}
                  </ul>
                  <p className="spx-proof__tell">{plate.tell}</p>
                </div>
              </div>
            </motion.div>
          </div>

          <div className="spx-sheet__band spx-sheet__band--foot" aria-hidden>
            <GuillocheBand height={14} waves={5} seed={41} />
          </div>
        </div>
      </Rise>

      {/* ── the grading, and then the three registers it produces ─────────── */}
      <Rise delay={0.04}>
        <div className="spx-grading mt-16">
          <h3 className="spx-grading__head">How each feature is verified</h3>
          <p className="spx-grading__body">
            A banknote&rsquo;s security features are graded by the instrument you
            check them with: Level&nbsp;1 in the hand, Level&nbsp;2 under a lamp or
            a UV light, Level&nbsp;3 in a laboratory. The same grading is used
            below — and it is the reason this sheet can be complete. A mechanism
            that only protects you once a deployment configures for it, or one
            that is built and tested but ships switched off, is printed at its own
            level with the precondition or the flag as the first line of the
            entry. Nothing is promoted by omission.
          </p>
        </div>
      </Rise>

      {TIERS.map((t, i) => (
        <Rise key={t.id} delay={i === 0 ? 0.04 : 0.02}>
          <TierRegister tier={t} />
        </Rise>
      ))}

      <Rise delay={0.03}>
        <div className="spx-notclaimed">
          <p className="spx-notclaimed__head">{NOT_CLAIMED.head}</p>
          <p className="spx-notclaimed__body">{NOT_CLAIMED.body}</p>
          <p className="spx-notclaimed__tell">{NOT_CLAIMED.tell}</p>
          <ul className="spx-notclaimed__cites">
            {NOT_CLAIMED.proof.map((c) => (
              <li key={`${c.path}${c.symbol ?? ""}`}>
                <Cite {...c} compact />
              </li>
            ))}
          </ul>
        </div>
      </Rise>
    </section>
  );
}
