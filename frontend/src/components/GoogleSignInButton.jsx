import React, { useState } from "react";
import { Loader2 } from "lucide-react";
import { isGoogleAuthConfigured, startGoogleSignIn } from "../lib/supabase";

/**
 * "Continue with Google" — shared by the login and registration screens.
 *
 * One component rather than the same markup on both pages, so the divider, the
 * icon and the error handling cannot drift apart. Styling deliberately mirrors the
 * existing buttons on those pages (rounded-2xl, same paddings and focus ring) so it
 * does not look bolted on.
 *
 * Renders nothing when Google sign-in is not configured, which keeps the login page
 * working unchanged if the Supabase variables are absent.
 */
export default function GoogleSignInButton({ label = "Continue with Google" }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!isGoogleAuthConfigured) return null;

  const handleClick = async () => {
    setError(null);
    setBusy(true);
    try {
      // Redirects the browser, so nothing below runs on success.
      await startGoogleSignIn();
    } catch (e) {
      setError(e?.message || "Could not start Google sign-in.");
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="relative">
        <div className="absolute inset-0 flex items-center" aria-hidden="true">
          <div className="w-full border-t border-gray-200" />
        </div>
        <div className="relative flex justify-center">
          <span className="bg-white px-3 text-xs uppercase tracking-wide text-gray-400">
            or
          </span>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-red-600">
          {error}
        </p>
      )}

      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        className="flex w-full items-center justify-center gap-3 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm font-semibold text-gray-700 shadow-sm transition hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-950 disabled:opacity-50"
      >
        {busy ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          /* Google's mark, inline so the button does not depend on a remote asset. */
          <svg className="h-5 w-5" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="#4285F4"
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"
            />
            <path
              fill="#34A853"
              d="M12 23c2.97 0 5.46-.98 7.28-2.65l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"
            />
            <path
              fill="#FBBC05"
              d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84Z"
            />
            <path
              fill="#EA4335"
              d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38Z"
            />
          </svg>
        )}
        {busy ? "Redirecting…" : label}
      </button>
    </div>
  );
}
