/**
 * Keep browser traffic on the origin the user actually opened. Vite proxies
 * `/api` to the local backend in development; production serves the same path
 * directly. Besides avoiding CORS, this keeps host-only session cookies valid
 * whether the app was opened as localhost, 127.0.0.1, or [::1].
 */
export const apiBase = "/api";
