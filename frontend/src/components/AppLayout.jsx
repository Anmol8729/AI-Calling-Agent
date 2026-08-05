import { Outlet } from "react-router-dom";
import { Suspense, useState } from "react";
import Navbar from "./Navbar";
import Sidebar from "./Sidebar";
import LoadingState from "./LoadingState";

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,#ffffff_0,#f7f7f8_34%,#eef0f3_100%)]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="lg:pl-72">
        <Navbar onMenuClick={() => setSidebarOpen(true)} />
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
