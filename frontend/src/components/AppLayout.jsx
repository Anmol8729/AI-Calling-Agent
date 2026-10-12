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
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,#ffffff_0,#f7f7f8_34%,#eef0f3_100%)]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="lg:pl-72">
        <Navbar onMenuClick={() => setSidebarOpen(true)} />
        {user?.tenant_status === "pending" && !user?.is_superadmin && (
          <div className="mx-4 mt-4 flex items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 sm:mx-6 lg:mx-8">
            <Clock className="h-5 w-5 shrink-0 text-amber-600" />
            <div>
              <span className="font-semibold">Account Pending Approval:</span> Your business account is awaiting administrator review. Outbound calling and full access will be enabled once approved.
            </div>
          </div>
        )}
        {user?.tenant_status === "suspended" && !user?.is_superadmin && (
          <div className="mx-4 mt-4 flex items-center gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 sm:mx-6 lg:mx-8">
            <AlertTriangle className="h-5 w-5 shrink-0 text-rose-600" />
            <div>
              <span className="font-semibold">Account Suspended:</span> This business account has been suspended. Please contact platform support.
            </div>
          </div>
        )}
        <main className="px-4 py-6 sm:px-6 lg:px-8">
          {/* Pages are code-split, so a chunk may still be loading. Keeping this
              boundary inside the layout means the sidebar and navbar stay put and
              only the content area shows a skeleton — no full-page flash. */}
          <Suspense fallback={<LoadingState />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
