import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Bot, Loader2 } from "lucide-react";
import api from "../lib/api";

export default function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!token) {
      setError("This reset link is missing its token.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await api.post("/auth/reset-password", { token, new_password: password });
      if (res.data?.success) setDone(true);
      else setError(res.data?.message || "This link is invalid or has expired.");
    } catch (err) {
      setError(err?.response?.data?.message || "This link is invalid or has expired.");
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
          <h2 className="mt-6 text-center text-3xl font-semibold tracking-tight text-gray-950">Set a new password</h2>
          <p className="mt-2 text-center text-sm text-gray-500">Choose a strong password for your account.</p>
        </div>

        {done ? (
          <div className="space-y-6">
            <div className="rounded-2xl border border-emerald-100 bg-emerald-50 p-4 text-sm text-emerald-800">
              Password set successfully. You can now sign in.
            </div>
            <Link to="/login" className="block text-center text-sm font-semibold text-gray-950 hover:underline">
              Go to sign in
            </Link>
          </div>
        ) : (
          <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
            {error && <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-600">{error}</div>}
            <div>
              <label htmlFor="new-password" className="text-sm font-medium text-gray-700">New password</label>
              <input
                id="new-password"
                type="password"
                required
                className="mt-1 block w-full rounded-2xl border border-gray-200 px-4 py-3 text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 sm:text-sm"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="confirm-password" className="text-sm font-medium text-gray-700">Confirm new password</label>
              <input
                id="confirm-password"
                type="password"
                required
                className="mt-1 block w-full rounded-2xl border border-gray-200 px-4 py-3 text-gray-900 placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 sm:text-sm"
                placeholder="••••••••"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex w-full justify-center rounded-2xl bg-brand-500 px-4 py-3 text-sm font-semibold text-white shadow hover:bg-brand-600 disabled:opacity-50"
            >
              {loading ? <Loader2 className="h-5 w-5 animate-spin" /> : "Set password"}
            </button>
            <p className="text-center text-sm text-gray-500">
              <Link to="/login" className="font-semibold text-gray-950 hover:underline">Back to sign in</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
