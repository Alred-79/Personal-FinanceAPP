import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useLenis } from "./hooks/useLenis";
import { useLandingTheme } from "./hooks/useLandingTheme";
import { Backdrop } from "./effects/Backdrop";
import { Nav } from "./sections/Nav";
import { AgentReadingRoom } from "./sections/AgentReadingRoom";
import { SpecimenSheet } from "./sections/SpecimenSheet";
import { Footer } from "./sections/Footer";
import { DemoLink } from "./demo";
import "./landing.css";

/**
 * "How it's built" — the technical annex, split off the consumer landing so the
 * front page can make one promise plainly. It holds the two engineer-facing
 * sections unchanged: the Reading Room (one agent request, scope by scope) and
 * the Specimen Sheet (each security mechanism with its file and test). Both were
 * art-directed for the landing's dark "Midnight Vault", so the page lives there.
 */
export default function HowItsBuilt() {
  useLandingTheme();
  useLenis();

  useEffect(() => {
    document.title = "How it’s built — The Ledger";
  }, []);

  return (
    <div className="landing-root dark relative min-h-screen overflow-x-clip bg-background text-foreground">
      <Backdrop />
      <Nav variant="subpage" />

      <main className="relative z-[1] mx-auto max-w-[1080px] px-4 sm:px-8">
        <header className="mx-auto max-w-[46rem] pt-[clamp(7rem,16vh,9rem)] text-center">
          <p className="dept-label">How it&rsquo;s built</p>
          <h1 className="mt-2 text-balance font-display font-semibold leading-[1.06]" style={{ fontSize: "clamp(2.2rem,5vw,3.6rem)" }}>
            The wiring behind the promises.
          </h1>
          <p className="mx-auto mt-4 max-w-[38rem] text-pretty text-[1.05rem] text-muted-foreground">
            The overview says your data stays yours and nothing moves without you.
            This page shows how: what a connected AI can and can&rsquo;t read, and
            the file and test behind every security claim.
          </p>
        </header>

        <AgentReadingRoom />
        <SpecimenSheet />

        <section className="mt-24 border-t border-rule-strong/40 pt-12 text-center">
          <h2 className="text-balance font-display font-semibold" style={{ fontSize: "clamp(1.6rem,3.6vw,2.3rem)" }}>
            Seen enough of the wiring?
          </h2>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <DemoLink className="press inline-block bg-primary px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em] text-primary-foreground">
              Try the demo
            </DemoLink>
            <Link
              to="/welcome"
              className="press border border-rule-strong/60 px-7 py-3.5 text-[0.9rem] font-semibold uppercase tracking-[0.04em]"
            >
              Back to the overview
            </Link>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
