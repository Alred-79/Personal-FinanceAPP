import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { loadCapabilities } from "@/lib/capabilities";

/** Same-origin entry: Login reads `?demo=1` and opens the showcase session. */
const LOCAL_DEMO = "/login?demo=1";

/**
 * The public showcase deployment (its own read-only database, DEMO_MODE_ENABLED)
 * — see docs/DEMO-MODE.md. Overridable at build time for forks and staging.
 */
const HOSTED_DEMO =
  import.meta.env.VITE_DEMO_URL ?? "https://persfin-demo-web-demo.up.railway.app/login?demo=1";

// One capability probe per page load, shared by every demo link on the page.
let localDemo: Promise<boolean> | null = null;
const servesLocalDemo = () =>
  (localDemo ??= loadCapabilities()
    .then((caps) => caps.demo === true)
    // A failed probe keeps the hosted link; it must never hide the demo.
    .catch(() => false));

/**
 * Where "Try the demo" goes: this instance's own demo when it serves one,
 * otherwise the hosted showcase. Starts on the hosted link so the button works
 * on the first frame and if the capability check fails.
 */
function useDemoHref(): string {
  const [href, setHref] = useState(HOSTED_DEMO);
  useEffect(() => {
    let active = true;
    void servesLocalDemo().then((local) => {
      if (active && local) setHref(LOCAL_DEMO);
    });
    return () => {
      active = false;
    };
  }, []);
  return href;
}

/** A link into the demo — a router Link on this origin, a plain anchor across. */
export function DemoLink({ className, children }: { className?: string; children: ReactNode }) {
  const href = useDemoHref();
  return href.startsWith("/") ? (
    <Link to={href} className={className}>
      {children}
    </Link>
  ) : (
    <a href={href} className={className}>
      {children}
    </a>
  );
}
