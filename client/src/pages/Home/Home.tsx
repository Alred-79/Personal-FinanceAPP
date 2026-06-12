/**
 * The two-homes IA switch (v4 §10.1).
 *
 * Full mode's home is the Expedition map; off and ambient keep Overview. The
 * routing reads ONLY the mode variable (the package-02 provider) — no other
 * signal decides the home surface.
 */
import { useFlags } from "@/store/gameMode";
import Overview from "@/pages/Overview/Overview";
import Expedition from "@/pages/Expedition/Expedition";

export default function Home() {
  const { terminal } = useFlags(); // terminal === full mode
  return terminal ? <Expedition /> : <Overview />;
}
