import { useEffect, useState } from "react";

import {
  loadCapabilities,
  type InstanceCapabilities,
} from "@/lib/capabilities";

let cached: InstanceCapabilities | null = null;
let request: Promise<InstanceCapabilities> | null = null;

export function useInstanceCapabilities(): InstanceCapabilities | null {
  const [value, setValue] = useState<InstanceCapabilities | null>(cached);

  useEffect(() => {
    let active = true;
    request ??= loadCapabilities();
    void request
      .then((capabilities) => {
        cached = capabilities;
        if (active) setValue(capabilities);
      })
      .catch(() => {
        request = null;
        if (active) setValue(null);
      });
    return () => {
      active = false;
    };
  }, []);

  return value;
}
