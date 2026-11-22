import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { Loader2 } from "lucide-react";
import GoogleSignInButton from "../components/GoogleSignInButton";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { login, error, loading } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email || !password) return;
    const success = await login(email, password);
    if (success) {
      navigate("/dashboard");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#EEF1F5] dark:bg-[#0A0A0A] px-4 py-12 sm:px-6 lg:px-8 transition-colors">
      <div className="w-full max-w-md space-y-6 rounded-[22px] border border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] p-8 shadow-[0_4px_20px_rgba(15,23,42,0.05)]">
        <div className="flex flex-col items-center">
          <div className="flex items-center justify-center mb-2">
            <img src="/logo-light.png" alt="Clarivo" className="h-11 w-auto object-contain dark:hidden" />
            <img src="/logo-dark.png" alt="Clarivo" className="h-11 w-auto object-contain hidden dark:block" />
          </div>
          <h2 className="mt-2 text-center text-[24px] font-semibold tracking-tight text-[#0F172A] dark:text-[#F5F7FA]">
            Welcome back
          </h2>
          <p className="mt-1 text-center text-[13px] text-[#64748B] dark:text-[#A1A1AA]">
            Log in to manage your AI receptionist
          </p>
        </div>

        {error && (
          <div className="rounded-[12px] bg-red-50 dark:bg-red-950/20 p-3.5 text-xs text-[#EF4444] border border-red-200 dark:border-red-900/30">
            {error}
          </div>
        )}

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-3">
            <div>
              <label htmlFor="email-address" className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] dark:text-[#A1A1AA]">
                Email Address
              </label>
              <input
                id="email-address"
                name="email"
                type="email"
                required
                className="mt-1 block w-full rounded-[12px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2.5 text-[13.5px] text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] focus:outline-none focus:ring-2 focus:ring-[#007BA7] transition-colors"
                placeholder="you@business.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            <div>
              <label htmlFor="password" className="text-[11px] font-semibold uppercase tracking-wider text-[#64748B] dark:text-[#A1A1AA]">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                required
                className="mt-1 block w-full rounded-[12px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] px-3.5 py-2.5 text-[13.5px] text-[#0F172A] dark:text-[#F5F7FA] placeholder-[#64748B] focus:outline-none focus:ring-2 focus:ring-[#007BA7] transition-colors"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <div className="flex justify-end pt-1">
            <Link to="/forgot-password" className="text-[12px] font-medium text-[#64748B] dark:text-[#A1A1AA] hover:text-[#007BA7] hover:underline">
              Forgot password?
            </Link>
          </div>

          <div>
            <button
              type="submit"
              disabled={loading}
              className="flex w-full justify-center rounded-full bg-[#007BA7] px-4 py-2.5 text-[13.5px] font-semibold text-white shadow hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-[#007BA7] disabled:opacity-50 transition-opacity cursor-pointer"
            >
              {loading ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                "Sign in"
              )}
            </button>
          </div>
        </form>

        <GoogleSignInButton label="Continue with Google" />

        <div className="text-center pt-2">
          <p className="text-[13px] text-[#64748B] dark:text-[#A1A1AA]">
            Don't have an account?{" "}
            <Link to="/register" className="font-semibold text-[#007BA7] hover:underline">
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
