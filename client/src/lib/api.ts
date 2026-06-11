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
const AUTH_PATHS = ["/refresh", "/token", "/signup", "/logout"];

let isRefreshing = false;
let failedQueue: Array<{ resolve: (value: unknown) => void; reject: (reason?: unknown) => void }> = [];

const processQueue = (error: unknown) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(null);
    }
  });
  failedQueue = [];
};

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
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then(() => api(originalRequest))
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        await api.post("/refresh/");
        processQueue(null);
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError);
        window.location.href = "/login";
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default api;
