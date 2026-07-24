import axios from "axios";
import { apiBase } from "./apiBase";

const api = axios.create({
  baseURL: apiBase,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

api.interceptors.request.use((config) => {
  // Ensure URL ends with trailing slash if no query parameters
  if (config.url) {
    if (config.url.includes("?")) {
      const [base, query] = config.url.split("?");
      config.url = `${base.endsWith("/") ? base : base + "/"}?${query}`;
    } else if (!config.url.endsWith("/")) {
      config.url = `${config.url}/`;
    }
  }
  return config;
});

// Auth endpoints must never trigger the refresh-retry flow. A 401 from
// /refresh/ in particular has to reject straight through: if it were queued
// like any other request, the outer `await api.post("/refresh/")` would wait
// on a promise that is only ever settled *after* that await resolves — a
// deadlock that leaves the app hung instead of redirecting to /login.
const AUTH_PATHS = [
  "/refresh",
  "/token",
  "/signup",
  "/logout",
  "/demo-login",
];

// A single in-flight refresh promise. Concurrent 401s (from the axios
// interceptor AND the raw-fetch SSE hook) all await THIS one promise, so the
// app issues exactly one POST /refresh/ no matter how many requests raced. The
// promise is cleared once it settles, so a later 401 can refresh again.
let refreshInFlight: Promise<void> | null = null;

export function unauthenticatedDestination(pathname: string, search = ""): string | null {
  if (pathname === "/login" || pathname === "/welcome") return null;
  if (pathname === "/") return "/welcome";
  return `/login?next=${encodeURIComponent(`${pathname}${search}`)}`;
}

/**
 * Refresh the session at most once across all concurrent callers. Both the axios
 * response interceptor and the SSE hook (raw fetch) call this so they share one
 * refresh. Rejects if the refresh itself fails (caller decides logout/redirect).
 */
export function refreshOnce(): Promise<void> {
  if (!refreshInFlight) {
    refreshInFlight = api
      .post("/refresh/")
      .then(() => undefined)
      .finally(() => {
        // Clear AFTER settle so the next 401 can start a fresh refresh.
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    const isAuthRequest = AUTH_PATHS.some((p) =>
      originalRequest?.url?.includes(p)
    );

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !isAuthRequest
    ) {
      originalRequest._retry = true;
      try {
        await refreshOnce();
        return api(originalRequest);
      } catch (refreshError) {
        // Don't bounce to /login if we're already on a public page. Otherwise a
        // failed background probe on a logged-out visit (e.g. GameModeProvider's
        // settings read, which fires above the auth boundary) turns into an
        // infinite reload loop: 401 → refresh fails → redirect → remount → 401…
        const destination = unauthenticatedDestination(
          window.location.pathname,
          window.location.search,
        );
        if (destination) window.location.href = destination;
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export default api;
