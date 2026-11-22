import { useState } from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";
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
    <div className="flex min-h-screen items-center justify-center bg-[#EEF1F5] dark:bg-[#0A0A0A] px-4 py-12">
      <div className="w-full max-w-md space-y-7 clarivo-panel p-8 shadow-xl">
        <div className="flex flex-col items-center">
          <div className="flex items-center justify-center mb-2">
            <img src="/logo-light.png" alt="Clarivo" className="h-10 w-auto object-contain dark:hidden" />
            <img src="/logo-dark.png" alt="Clarivo" className="h-10 w-auto object-contain hidden dark:block" />
          </div>
          <h2 className="mt-2 text-center text-2xl font-semibold tracking-tight text-[#0F172A] dark:text-[#F5F7FA]">Reset your password</h2>
          <p className="mt-1.5 text-center text-xs text-[#64748B] dark:text-[#A1A1AA]">We'll email you a secure reset link.</p>
        </div>

        {done ? (
          <div className="space-y-6">
            <div className="rounded-[18px] border border-emerald-200/60 bg-emerald-50/70 dark:bg-emerald-950/20 dark:border-emerald-900/40 p-4 text-xs font-medium text-emerald-800 dark:text-emerald-300">
              If that email is registered, a reset link has been sent. Check your inbox.
            </div>
            <Link to="/login" className="block text-center text-xs font-semibold uppercase tracking-wider text-[#007BA7] hover:underline">
              Back to sign in
            </Link>
          </div>
        ) : (
          <form className="mt-6 space-y-5" onSubmit={handleSubmit}>
            {error && <div className="rounded-[18px] border border-red-200/60 bg-red-50/70 dark:bg-red-950/20 dark:border-red-900/40 p-4 text-xs font-medium text-red-700 dark:text-red-400">{error}</div>}
            <div>
              <label htmlFor="email" className="block text-xs font-medium text-[#64748B] dark:text-[#A1A1AA] mb-1.5">Email Address</label>
              <input
                id="email"
                type="email"
                required
                className="block w-full rounded-[12px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#FFFFFF] dark:bg-[#171A1D] px-3.5 py-2.5 text-xs text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] dark:placeholder-[#A1A1AA] focus:border-[#007BA7] focus:outline-none focus:ring-1 focus:ring-[#007BA7]"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex w-full justify-center rounded-full bg-[#007BA7] px-4 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-[#00668A] disabled:opacity-50 transition"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send reset link"}
            </button>
            <p className="text-center text-xs text-[#64748B] dark:text-[#A1A1AA]">
              Remembered it? <Link to="/login" className="font-semibold text-[#007BA7] hover:underline">Sign in</Link>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
