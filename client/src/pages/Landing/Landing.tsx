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
import { EngineersBridge } from "./sections/EngineersBridge";
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
 * accent decorates chrome only. Composed from sections/*.
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
          {/* One promise, then its proof, for a visitor who has 30 seconds:
              the Hero states it (safe to spend before payday, as a two-sided
              coin), the Forecast shows how the number is made and how a
              decision moves it, the Instruments name what feeds it, and the
              Vault says what the product promises about your data.

              The engineer-facing depth (the Reading Room's single agent request
              and the Specimen Sheet's file-and-test citations) lives on
              /how-its-built; EngineersBridge hands off to it. */}
          <Hero />
          <Forecast />
          <Instruments />
          <VaultDoor />
          <Security />
          <EngineersBridge />
          <FinalCTA />
        </div>

        <Footer />
      </div>
    </VaultLightsProvider>
  );
}
