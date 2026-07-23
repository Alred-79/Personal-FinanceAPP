import { useLenis } from "./hooks/useLenis";
import { useLandingTheme } from "./hooks/useLandingTheme";
import { VaultLightsProvider } from "./hooks/useVaultLights";
import { Backdrop } from "./effects/Backdrop";
import { VaultLightSwitch } from "./effects/VaultLightSwitch";
import { Nav } from "./sections/Nav";
import { Hero } from "./sections/Hero";
import { Forecast } from "./sections/Forecast";
import { Instruments } from "./sections/Instruments";
import { VaultDoor } from "./sections/VaultDoor";
import { Security } from "./sections/Security";
import { AgentReadingRoom } from "./sections/AgentReadingRoom";
import { SpecimenSheet } from "./sections/SpecimenSheet";
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
    <VaultLightsProvider>
      <div className="landing-root relative min-h-screen overflow-x-clip bg-background text-foreground">
        {/* living backdrop: static guilloché base + cursor-reactive WebGL field */}
        <Backdrop />

        <Nav />

        {/* the vault's own light-switch — appears only past the VaultDoor */}
        <VaultLightSwitch />

        <div className="relative z-[1] mx-auto max-w-[1080px] px-4 sm:px-8">
          {/* Lead with the Hero, then the simulated-overdraft Forecast right
              below it (its original top-of-page placement), followed by the
              working tools, the vault's trust guarantees, and — last, on the
              dark side — the Reading Room where an AI reads the ledger under
              scopes the visitor controls.

              Three registers on security, in widening depth and never repeating
              each other: the Vault says what the product PROMISES you, the
              Reading Room shows what happens to ONE REQUEST, and the Specimen
              Sheet — the technical annex — documents HOW THE SURFACE IS BUILT
              and cites the file and test for each claim. */}
          <Hero />
          <Forecast />
          <Instruments />
          <VaultDoor />
          <Security />
          <AgentReadingRoom />
          <SpecimenSheet />
          <FinalCTA />
        </div>

        <Footer />
      </div>
    </VaultLightsProvider>
  );
}
