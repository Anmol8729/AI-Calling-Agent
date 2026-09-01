import { useState } from "react";
import { Link } from "react-router-dom";
import { Bot, Loader2 } from "lucide-react";
import api from "../lib/api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email) return;
    setLoading(true);
    setError("");
    try {
      const res = await api.post("/auth/forgot-password", { email });
      if (res.data?.success) setDone(true);
      else setError(res.data?.message || "Something went wrong.");
    } catch {
      setError("Could not reach the server.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 py-12">
      <div className="w-full max-w-md space-y-8 rounded-3xl border border-gray-200 bg-white p-8 shadow-xl shadow-gray-900/5">
        <div className="flex flex-col items-center">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-brand-500 text-white shadow-lg shadow-gray-950/20">
            <Bot className="h-6 w-6" />
          </div>
          <h2 className="mt-6 text-center text-3xl font-semibold tracking-tight text-gray-950">Reset your password</h2>
          <p className="mt-2 text-center text-sm text-gray-500">We'll email you a secure reset link.</p>
        </div>

        {done ? (
          <div className="space-y-6">
            <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-800">
              If that email is registered, a reset link has been sent. Check your inbox.
            </div>
            <Link to="/login" className="block text-center text-sm font-semibold text-gray-950 hover:underline">
              Back to sign in
            </Link>
          </div>
        ) : (
          <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
            {error && <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-600">{error}</div>}
            <div>
              <label htmlFor="email" className="text-sm font-medium text-gray-700">Email Address</label>
              <input
                id="email"
                type="email"
                required
                className="mt-1 block w-full rounded-2xl border border-gray-200 px-4 py-3 text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 sm:text-sm"
                placeholder="Email address"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex w-full justify-center rounded-2xl bg-brand-500 px-4 py-3 text-sm font-semibold text-white shadow hover:bg-brand-600 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : "Send reset link"}
            </button>
            <p className="text-center text-sm text-gray-500">
              Remembered it? <Link to="/login" className="font-semibold text-gray-950 hover:underline">Sign in</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
