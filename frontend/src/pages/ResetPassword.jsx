import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Loader2 } from "lucide-react";
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
    <div className="flex min-h-screen items-center justify-center bg-[#EEF1F5] dark:bg-[#0A0A0A] px-4 py-12">
      <div className="w-full max-w-md space-y-7 clarivo-panel p-8 shadow-xl">
        <div className="flex flex-col items-center">
          <div className="flex items-center justify-center mb-2">
            <img src="/logo-light.png" alt="Clarivo" className="h-10 w-auto object-contain dark:hidden" />
            <img src="/logo-dark.png" alt="Clarivo" className="h-10 w-auto object-contain hidden dark:block" />
          </div>
          <h2 className="mt-2 text-center text-2xl font-semibold tracking-tight text-[#0F172A] dark:text-[#F5F7FA]">Set a new password</h2>
          <p className="mt-1.5 text-center text-xs text-[#64748B] dark:text-[#A1A1AA]">Choose a strong password for your account.</p>
        </div>

        {done ? (
          <div className="space-y-6">
            <div className="rounded-[18px] border border-emerald-200/60 bg-emerald-50/70 dark:bg-emerald-950/20 dark:border-emerald-900/40 p-4 text-xs font-medium text-emerald-800 dark:text-emerald-300">
              Password set successfully. You can now sign in.
            </div>
            <Link to="/login" className="block text-center text-xs font-semibold uppercase tracking-wider text-[#007BA7] hover:underline">
              Go to sign in
            </Link>
          </div>
        ) : (
          <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
            {error && <div className="rounded-[18px] border border-red-200/60 bg-red-50/70 dark:bg-red-950/20 dark:border-red-900/40 p-4 text-xs font-medium text-red-700 dark:text-red-400">{error}</div>}
            <div>
              <label htmlFor="new-password" className="block text-xs font-medium text-[#64748B] dark:text-[#A1A1AA] mb-1.5">New password</label>
              <input
                id="new-password"
                type="password"
                required
                className="block w-full rounded-[12px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#FFFFFF] dark:bg-[#171A1D] px-3.5 py-2.5 text-xs text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] dark:placeholder-[#A1A1AA] focus:border-[#007BA7] focus:outline-none focus:ring-1 focus:ring-[#007BA7]"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="confirm-password" className="block text-xs font-medium text-[#64748B] dark:text-[#A1A1AA] mb-1.5">Confirm new password</label>
              <input
                id="confirm-password"
                type="password"
                required
                className="block w-full rounded-[12px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#FFFFFF] dark:bg-[#171A1D] px-3.5 py-2.5 text-xs text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] dark:placeholder-[#A1A1AA] focus:border-[#007BA7] focus:outline-none focus:ring-1 focus:ring-[#007BA7]"
                placeholder="••••••••"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex w-full justify-center rounded-full bg-[#007BA7] px-4 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-[#00668A] disabled:opacity-50 transition"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Set password"}
            </button>
            <p className="text-center text-xs text-[#64748B] dark:text-[#A1A1AA]">
              <Link to="/login" className="font-semibold text-[#007BA7] hover:underline">Back to sign in</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
