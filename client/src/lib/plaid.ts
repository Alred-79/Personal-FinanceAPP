import { useEffect, useState } from "react";

/** The Plaid Link handler the SDK's create() returns. */
export interface PlaidHandler {
  open: () => void;
  /** Tears down the Link iframe/listeners — present on the real SDK handler. */
  destroy?: () => void;
}

declare global {
  interface Window {
    // Optional: the Plaid Link <script> loads async, so this may be undefined
    // until it parses. Callers must guard before calling create().
    Plaid?: {
      create: (config: {
        token: string;
        onSuccess: (
          publicToken: string,
          metadata: { institution: { name: string } }
        ) => void;
        onExit: (err: Error | null) => void;
        onEvent: (eventName: string, metadata: unknown) => void;
      }) => PlaidHandler;
    };
  }
}

/**
 * Poll for the async-loaded Plaid Link script so a Connect button isn't dead on
 * a slow network (the <script> may not be parsed when the component first
 * renders). Returns true once window.Plaid is available.
 */
export function usePlaidReady(): boolean {
  const [ready, setReady] = useState(
    () => typeof window !== "undefined" && !!window.Plaid
  );
  useEffect(() => {
    if (ready) return;
    const id = setInterval(() => {
      if (window.Plaid) {
        setReady(true);
        clearInterval(id);
      }
    }, 200);
    return () => clearInterval(id);
  }, [ready]);
  return ready;
}
