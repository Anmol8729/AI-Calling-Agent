import { Outlet } from "react-router-dom";
import { Suspense, useState } from "react";
import { Clock, AlertTriangle } from "lucide-react";
import Navbar from "./Navbar";
import Sidebar from "./Sidebar";
import LoadingState from "./LoadingState";
import { useAuthStore } from "../store/authStore";

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const user = useAuthStore((s) => s.user);

  return (
    <div className="min-h-screen bg-[#EEF1F5] dark:bg-[#0A0A0A] text-[#0F172A] dark:text-[#F5F7FA] p-3 sm:p-4 lg:p-6 transition-colors duration-200">
      <div className="max-w-[1440px] mx-auto flex flex-col gap-4">
        {/* Floating Top Bar (Header) */}
        <Navbar onMenuClick={() => setSidebarOpen(true)} />

        {/* Tenant Status Banners */}
        {user?.tenant_status === "pending" && !user?.is_superadmin && (
          <div className="flex items-center gap-3 rounded-[18px] border border-amber-200 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-900/50 px-4 py-3 text-sm text-amber-800 dark:text-amber-300">
            <Clock className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div>
              <span className="font-semibold">Account Pending Approval:</span> Your business account is awaiting administrator review. Outbound calling and full access will be enabled once approved.
            </div>
          </div>
        )}
        {user?.tenant_status === "suspended" && !user?.is_superadmin && (
          <div className="flex items-center gap-3 rounded-[18px] border border-rose-200 bg-rose-50 dark:bg-rose-950/30 dark:border-rose-900/50 px-4 py-3 text-sm text-rose-800 dark:text-rose-300">
            <AlertTriangle className="h-5 w-5 shrink-0 text-rose-600 dark:text-rose-400" />
            <div>
              <span className="font-semibold">Account Suspended:</span> This business account has been suspended. Please contact platform support.
            </div>
          </div>
        )}

        {/* Body Area with Left Floating Rail & Main Content */}
        <div className="flex gap-4 items-start w-full">
          <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
          <main className="flex-1 flex flex-col gap-4 min-w-0">
            <Suspense fallback={<LoadingState />}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  );
}
