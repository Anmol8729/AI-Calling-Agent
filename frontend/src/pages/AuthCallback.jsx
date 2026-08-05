import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Loader2 } from "lucide-react";
import { useAuthStore } from "../store/authStore";
import {
  clearSupabaseSession,
  getSupabaseAccessToken,
  isGoogleAuthConfigured,
} from "../lib/supabase";

/**
 * Where Google sends the browser back to.
 *
 * Reads the Supabase session the client just established from the callback URL,
 * exchanges it for one of this app's own tokens, then drops the Supabase session so
 * only one long-lived session remains in the browser.
 *
 * Public route by design: at this point the user has no app session yet, so it
 * cannot sit behind ProtectedRoute.
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const loginWithGoogle = useAuthStore((s) => s.loginWithGoogle);
  const [error, setError] = useState(null);
  // React 18 StrictMode runs effects twice in development. Without this guard the
  // token would be exchanged twice, producing a confusing duplicate audit entry.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    (async () => {
      if (!isGoogleAuthConfigured) {
        setError("Google sign-in is not configured for this deployment.");
        return;
      }

      // Google reports a refusal (for example the user cancelled) in the URL rather
      // than by failing the redirect.
      const params = new URLSearchParams(window.location.search);
      const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
      const providerError =
        params.get("error_description") ||
        params.get("error") ||
        hash.get("error_description") ||
        hash.get("error");
      if (providerError) {
        setError(decodeURIComponent(providerError));
        return;
      }

      let supabaseToken;
      try {
        supabaseToken = await getSupabaseAccessToken();
      } catch (e) {
        setError(e?.message || "Could not complete Google sign-in.");
        return;
      }
      if (!supabaseToken) {
        setError("Google sign-in did not complete. Please try again.");
        return;
      }

      const result = await loginWithGoogle(supabaseToken);
      // The Supabase session has done its job; our own token is what the app uses.
      await clearSupabaseSession();

      if (!result.ok) {
        // loginWithGoogle already put the reason in the store; surface it here too
        // so the user is not left on a blank screen.
        setError(useAuthStore.getState().error || "Google sign-in failed.");
        return;
      }

      // A brand new account has no business details yet, so start it in Setup.
      navigate(result.isNewAccount ? "/setup" : "/dashboard", { replace: true });
    })();
  }, [loginWithGoogle, navigate]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-md space-y-6 rounded-3xl border border-gray-200 bg-white p-8 text-center shadow-xl shadow-gray-900/5">
        <div className="flex justify-center">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-gray-950 text-white shadow-lg shadow-gray-950/20">
            <Bot className="h-6 w-6" />
          </div>
        </div>

        {error ? (
          <>
            <h1 className="text-xl font-semibold text-gray-950">
              Couldn&apos;t finish signing in
            </h1>
            <p className="text-sm text-red-600">{error}</p>
            <button
              type="button"
              onClick={() => navigate("/login", { replace: true })}
              className="w-full rounded-2xl bg-gray-950 px-4 py-3 text-sm font-semibold text-white shadow hover:bg-gray-900 focus:outline-none focus:ring-2 focus:ring-gray-950"
            >
              Back to sign in
            </button>
          </>
        ) : (
          <>
            <h1 className="text-xl font-semibold text-gray-950">Signing you in…</h1>
            <p className="text-sm text-gray-500">
              Finishing up with Google. This only takes a moment.
            </p>
            <Loader2
              className="mx-auto h-6 w-6 animate-spin text-gray-400"
              aria-label="Signing in"
            />
          </>
        )}
      </div>
    </div>
  );
}
