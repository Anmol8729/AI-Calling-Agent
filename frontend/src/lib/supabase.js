// Supabase client used for ONE thing: Google sign-in.
//
// It is not this app's session store. After Google redirects back, we hand the
// resulting Supabase token to POST /api/auth/oauth/google, the backend verifies it
// and returns THIS app's own token, and the Supabase session is then signed out.
// That keeps exactly one long-lived session in the browser instead of two, and
// leaves all the existing controls (tenant scoping, roles, revocation, lockout,
// audit) in the path they already occupy.
//
// Only the ANON key belongs here. Vite inlines every VITE_-prefixed variable into
// the JavaScript bundle, so anything named this way is public by definition. The
// SERVICE ROLE key must never be given a VITE_ name — it bypasses Row Level
// Security and would be readable by anyone who opens the bundle.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

// Google sign-in is optional: with these unset the app runs exactly as before and
// the button simply is not rendered. A missing variable degrades a feature instead
// of breaking the login page.
//
// Note this is a plain env check with NO import of the SDK, which is what lets the
// login page decide whether to show the button without paying for the library.
export const isGoogleAuthConfigured = Boolean(supabaseUrl && supabaseAnonKey);

// The SDK is ~36 KB gzipped. Importing it at module scope pulled it into the initial
// bundle, because Login.jsx is deliberately eager (it is the first screen anyone
// not signed in sees) — that undid part of the code-splitting work and slowed the
// first paint for every visitor, to support a button most never click.
//
// Loading it dynamically on first use keeps it out of the initial download. It is
// fetched when someone actually presses "Continue with Google", or when the callback
// page runs — both moments where a brief wait is already expected.
let clientPromise = null;

function loadClient() {
  if (!isGoogleAuthConfigured) return Promise.resolve(null);
  if (!clientPromise) {
    clientPromise = import("@supabase/supabase-js").then(({ createClient }) =>
      createClient(supabaseUrl, supabaseAnonKey, {
        auth: {
          // PKCE (the default) is the stronger flow, but it needs somewhere to keep
          // the code verifier across the redirect to Google and back — so session
          // storage has to stay on. We sign out of Supabase as soon as the token
          // has been exchanged, so nothing lingers.
          flowType: "pkce",
          persistSession: true,
          // Lets the client pick the authorisation code out of the callback URL and
          // complete the exchange itself.
          detectSessionInUrl: true,
          autoRefreshToken: false,
        },
      }),
    );
  }
  return clientPromise;
}

/**
 * Start Google sign-in. Redirects the browser; nothing after this runs.
 */
export async function startGoogleSignIn() {
  const supabase = await loadClient();
  if (!supabase) {
    throw new Error("Google sign-in is not configured.");
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: `${window.location.origin}/auth/callback`,
      queryParams: {
        // Ask Google for a fresh choice rather than silently reusing whichever
        // account the browser signed in with last.
        prompt: "select_account",
      },
    },
  });
  if (error) throw error;
}

/**
 * The Supabase access token from the completed redirect, or null.
 */
export async function getSupabaseAccessToken() {
  const supabase = await loadClient();
  if (!supabase) return null;
  // Resolves after the client has finished processing the code in the URL.
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  return data?.session?.access_token ?? null;
}

/**
 * Drop the Supabase session once its token has been exchanged for ours.
 *
 * Best-effort: our own session is already established by this point, so a failure
 * here must not block the user. Worst case a short-lived token expires on its own.
 */
export async function clearSupabaseSession() {
  const supabase = await loadClient();
  if (!supabase) return;
  try {
    await supabase.auth.signOut();
  } catch {
    // nothing to do
  }
}
