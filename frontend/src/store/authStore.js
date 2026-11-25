import { create } from "zustand";
import api from "../lib/api";

// Store a successful sign-in. Extracted so password login, registration and Google
// sign-in all persist the session identically — three copies of this would be three
// chances for them to drift apart.
function adoptSession(set, data) {
  const safeUser = { ...data };
  delete safeUser.access_token;

  if (data.cookie_auth || data.is_superadmin) {
    // Admin session tokens live strictly in HttpOnly cookies, never in localStorage.
    localStorage.removeItem("token");
  } else if (data.access_token) {
    localStorage.setItem("token", data.access_token);
  }
  localStorage.setItem("user", JSON.stringify(safeUser));
  set({
    token: data.cookie_auth || data.is_superadmin ? null : (data.access_token || null),
    user: safeUser,
    isAuthenticated: true,
    loading: false,
    error: null,
  });
}

// The API returns errors in a few shapes: FastAPI validation arrays, our own
// `message`, or a bare `error`. Unwrapping it in one place keeps the messages
// consistent across every auth screen.
function extractAuthError(err, fallback) {
  const resData = err.response?.data;
  if (!resData) return fallback;
  if (resData.detail) {
    if (Array.isArray(resData.detail)) {
      return resData.detail
        .map((d) => `${d.loc[d.loc.length - 1]}: ${d.msg}`)
        .join(", ");
    }
    return resData.detail;
  }
  return resData.message || resData.error || fallback;
}

export const useAuthStore = create((set) => ({
  token: localStorage.getItem("token") || null,
  user: (() => {
    try {
      const u = localStorage.getItem("user");
      return u && u !== "undefined" ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  })(),
  isAuthenticated: (() => {
    if (localStorage.getItem("token")) return true;
    try {
      const u = localStorage.getItem("user");
      return !!(u && u !== "undefined" && JSON.parse(u)?.cookie_auth);
    } catch {
      return false;
    }
  })(),
  loading: false,
  error: null,

  login: async (email, password) => {
    set({ loading: true, error: null });
    try {
      const response = await api.post(`/auth/login`, { email, password });
      const { success, data, message } = response.data;
      
      if (success && (data?.access_token || data?.cookie_auth)) {
        adoptSession(set, data);
        return true;
      } else {
        set({ error: message || "Invalid credentials", loading: false });
        return false;
      }
    } catch (err) {
      set({ error: extractAuthError(err, "Login connection failed"), loading: false });
      return false;
    }
  },

  // No `did` argument any more. A phone number has to be attached to the tenant's own
  // SIP trunk and proven by a real inbound call before it can route, and signup can do
  // neither — the backend now ignores the field. Numbers are added in Setup.
  register: async (email, password, name, clinicName, industry) => {
    set({ loading: true, error: null });
    try {
      const response = await api.post(`/auth/register`, {
        email,
        password,
        name,
        clinic_name: clinicName,
        role: "doctor",
        industry
      });
      
      const { success, data, message } = response.data;
      if (success && data.access_token) {
        adoptSession(set, data);
        return true;
      } else {
        set({ error: message || "Registration failed", loading: false });
        return false;
      }
    } catch (err) {
      set({ error: extractAuthError(err, "Registration connection failed"), loading: false });
      return false;
    }
  },

  // Finish Google sign-in: exchange the Supabase token for one of ours.
  //
  // Reuses `adoptSession` below, so the stored shape is identical to a password
  // login and nothing downstream needs to know how the person signed in.
  loginWithGoogle: async (supabaseAccessToken) => {
    set({ loading: true, error: null });
    try {
      const response = await api.post("/auth/oauth/google", {
        access_token: supabaseAccessToken,
      });
      const { success, data, message } = response.data;
      if (success && (data?.access_token || data?.cookie_auth)) {
        adoptSession(set, data);
        return { ok: true, isNewAccount: Boolean(data.is_new_account) };
      }
      set({ error: message || "Google sign-in failed", loading: false });
      return { ok: false };
    } catch (err) {
      set({ error: extractAuthError(err, "Google sign-in failed"), loading: false });
      return { ok: false };
    }
  },

  // Replace the stored session token in place. Used after a password change,
  // which revokes every existing token server-side (including this tab's) and
  // returns a fresh one — without adopting it the next request would 401.
  setToken: (accessToken) => {
    if (!accessToken) return;
    localStorage.setItem("token", accessToken);
    set({ token: accessToken, isAuthenticated: true });
  },

  logout: async () => {
    // Ask the server to revoke the active session and clear HttpOnly admin cookies.
    try {
      await api.post("/auth/logout");
    } catch {
      // already signed out, offline, or token expired — nothing to do
    }
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    set({ token: null, user: null, isAuthenticated: false });
  }
}));
