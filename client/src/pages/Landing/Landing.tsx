import { useLenis } from "./hooks/useLenis";
import { useLandingTheme } from "./hooks/useLandingTheme";
import { Backdrop } from "./effects/Backdrop";
import { Nav } from "./sections/Nav";
import { Hero } from "./sections/Hero";
import { HowItWorks } from "./sections/HowItWorks";
import { Modes } from "./sections/Modes";
import { Trust } from "./sections/Trust";
import { FinalCTA } from "./sections/FinalCTA";
import { Footer } from "./sections/Footer";
import "./landing.css";

/** Public front door: universal decision layer, optional Work Money specialization. */
export default function Landing() {
  useLandingTheme();
  useLenis();

  return (
    <div className="landing-root min-h-screen overflow-x-clip bg-background text-foreground">
      <Backdrop />
      <Nav />

      <main className="relative z-[1]">
        <div className="decision-page-shell">
          <Hero />
          <HowItWorks />
          <Modes />
        </div>
        <Trust />
        <div className="decision-page-shell decision-page-shell--closing">
          <FinalCTA />
        </div>
      </main>

      <Footer />
    </div>
  );
}
