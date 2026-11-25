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

const api = axios.create({ baseURL, withCredentials: true });

function readCookie(name) {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

// Attach the JWT (when present in localStorage for clinic users) and CSRF token
// (for HttpOnly cookie-authenticated admin sessions) on every request.
api.interceptors.request.use((config) => {
  config.headers = config.headers || {};
  const token = localStorage.getItem("token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  const csrf = readCookie("clarivo_csrf_token");
  if (csrf) {
    config.headers["X-CSRF-Token"] = csrf;
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
