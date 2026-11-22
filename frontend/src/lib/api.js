import axios from "axios";

// Base URL of the FastAPI backend. Configurable via Vite env (frontend/.env).
// Defaults to relative "/api" so requests automatically go to the current host
// through Vite proxy or FastAPI static mount without cross-origin port mismatch.
// In external static deployments (like Cloudflare Pages on app.clarivo.net.in),
// it routes to the dedicated API subdomain https://api.clarivo.net.in/api.
export function getBaseUrl() {
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host === "app.clarivo.net.in" || host === "clarivo-dashboard-git.pages.dev") {
      return (import.meta.env.VITE_API_URL || "https://api.clarivo.net.in/api").replace(/\/+$/, "");
    }
  }
  return (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");
}

const baseURL = getBaseUrl();

const api = axios.create({ baseURL });

// Attach the JWT (when present) from localStorage on every request. Reading it
// per-request means auth survives full page reloads with no manual header
// bookkeeping, and logout takes effect as soon as the token is cleared.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On an expired/invalid session (401), clear auth and bounce to the login page.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

export default api;
