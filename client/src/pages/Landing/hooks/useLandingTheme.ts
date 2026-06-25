import { useEffect } from "react";

/**
 * The landing art-directs its own light→dark scroll journey, so while it is
 * mounted it takes over theme control: it forces the light "Ledger Paper"
 * baseline on <html> (the journey itself adds `.dark` to the landing root for the
 * lower "Midnight Vault" sections) and restores the visitor's saved theme on
 * unmount. This keeps the journey deterministic even for dark-preference users
 * without disturbing the rest of the app.
 */
export function useLandingTheme() {
  useEffect(() => {
    const html = document.documentElement;
    const hadDark = html.classList.contains("dark");
    html.classList.remove("dark");
    return () => {
      if (hadDark) html.classList.add("dark");
    };
  }, []);
}
