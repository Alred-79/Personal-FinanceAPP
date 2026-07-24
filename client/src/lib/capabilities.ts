import api from "./api";

export const ASSISTANT_CAPABILITY_KEY = "ledger:assistant-configured";

export interface InstanceCapabilities {
  registration_open: boolean;
  demo: boolean;
  plaid: boolean;
  assistant: boolean;
  web_search: boolean;
  unstructured_import: boolean;
}

export async function loadCapabilities(): Promise<InstanceCapabilities> {
  const response = await api.get<InstanceCapabilities>("/capabilities");
  try {
    sessionStorage.setItem(
      ASSISTANT_CAPABILITY_KEY,
      String(response.data.assistant === true),
    );
  } catch {
    // Storage can be unavailable in hardened/private browser contexts.
  }
  return response.data;
}
