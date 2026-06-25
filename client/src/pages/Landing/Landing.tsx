import { useLenis } from "./hooks/useLenis";
import { useLandingTheme } from "./hooks/useLandingTheme";
import { Backdrop } from "./effects/Backdrop";
import { Nav } from "./sections/Nav";
import { Hero } from "./sections/Hero";
import { Forecast } from "./sections/Forecast";
import { Instruments } from "./sections/Instruments";
import { VaultDoor } from "./sections/VaultDoor";
import { Security } from "./sections/Security";
import { Cabinet } from "./sections/Cabinet";
import { FinalCTA } from "./sections/FinalCTA";
import { Footer } from "./sections/Footer";
import "./landing.css";

/**
 * The Ledger — "The Polymer Vault" public marketing landing, shown before /login.
 * Standalone (no AppShell), like /login. Re-skinned onto the existing "Engraver's
 * Ledger" system (same tokens, primitives, color law) and pushed toward a
 * captivating, high-end experience: a light→dark scroll journey, a living WebGL
 * guilloché field and a struck 3D coin, holographic foil and frosted polymer
 * "security windows". Money figures stay sober (.figure / .intaglio); the gold
 * accent decorates chrome only. Composed from sections/*; the scroll journey,
 * 3D coin, and polymer-glass layers arrive in later phases.
 */
export default function Landing() {
  useLandingTheme();
  useLenis();

  return (
    <div className="landing-root relative min-h-screen overflow-x-clip bg-background text-foreground">
      {/* living backdrop: static guilloché base + cursor-reactive WebGL field */}
      <Backdrop />

      <Nav />

      <div className="relative z-[1] mx-auto max-w-[1080px] px-4 sm:px-8">
        <Hero />
        <Forecast />
        <Instruments />
        <VaultDoor />
        <Security />
        <Cabinet />
        <FinalCTA />
      </div>

      <Footer />
    </div>
  );
}
