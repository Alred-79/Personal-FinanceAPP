import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/**
 * Vault lights — a manual override of the light→dark journey, scoped to the dark
 * "vault" half of the landing.
 *
 * The scroll journey (useThemeJourney) darkens the page past the VaultDoor. This
 * context lets a physical light-switch flip the vault region back to light:
 *   - `lightsOn`   — true → force the dark zone to render light ("lights on").
 *   - `inDarkZone` — true once the viewport is at/below the VaultDoor threshold;
 *                    the switch only exists here (it's the vault's own control).
 *
 * useThemeJourney consumes `lightsOn` (factoring it into the .dark toggle) and
 * publishes `inDarkZone`; the switch consumes `inDarkZone` and toggles `lightsOn`.
 * A safe default value keeps both usable outside a provider (isolated tests).
 */
type VaultLightsValue = {
  lightsOn: boolean;
  setLightsOn: (on: boolean) => void;
  inDarkZone: boolean;
  setInDarkZone: (v: boolean) => void;
};

const VaultLightsContext = createContext<VaultLightsValue>({
  lightsOn: false,
  setLightsOn: () => {},
  inDarkZone: false,
  setInDarkZone: () => {},
});

export function VaultLightsProvider({ children }: { children: ReactNode }) {
  const [lightsOn, setLightsOn] = useState(false);
  const [inDarkZone, setInDarkZone] = useState(false);
  const value = useMemo(
    () => ({ lightsOn, setLightsOn, inDarkZone, setInDarkZone }),
    [lightsOn, inDarkZone]
  );
  return <VaultLightsContext.Provider value={value}>{children}</VaultLightsContext.Provider>;
}

export function useVaultLights(): VaultLightsValue {
  return useContext(VaultLightsContext);
}
