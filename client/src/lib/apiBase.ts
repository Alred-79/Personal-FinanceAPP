/**
 * Base URL for the backend API. In dev the Vite server runs on port 5173 while
 * the API is on 8000, so we point at the absolute origin; in every other case
 * (production build served by the backend) the relative `/api` prefix is used.
 */
export const apiBase =
  window.location.port === "5173" ? "http://localhost:8000/api" : "/api";
