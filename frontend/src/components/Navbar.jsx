import { useEffect } from "react";
import { Building2, Menu } from "lucide-react";
import { Button } from "./ui/Button";
import NotificationsBell from "./NotificationsBell";
import { useAuthStore } from "../store/authStore";
import { useClinicStore } from "../store/clinicStore";

export default function Navbar({ onMenuClick }) {
  const { user } = useAuthStore();
  const businessName = useClinicStore((s) => s.clinic?.name);
  const fetchClinic = useClinicStore((s) => s.fetchClinic);

  // Make the top bar self-sufficient: pull the clinic (guarded, shared) so the
  // business name shows even if the sidebar hasn't triggered the fetch yet.
  useEffect(() => {
    fetchClinic();
  }, [fetchClinic]);

  const userName = user?.name || "User";
  const userRole = user?.role
    ? user.role.charAt(0).toUpperCase() + user.role.slice(1)
    : "Team member";
  const initials =
    userName
      .trim()
      .split(/\s+/)
      .map((word) => word[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "U";

  return (
    <header className="sticky top-0 z-30 border-b border-gray-200/80 bg-white/80 backdrop-blur-xl">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-6 lg:px-8">
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onMenuClick} aria-label="Open menu">
          <Menu className="h-5 w-5" />
        </Button>

        {businessName && (
          <div className="hidden min-w-0 items-center gap-2 rounded-2xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-800 shadow-sm md:flex">
            <Building2 className="h-4 w-4 shrink-0 text-gray-400" />
            <span className="max-w-[220px] truncate">{businessName}</span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-3">
          <NotificationsBell />
          <div className="flex items-center gap-3 rounded-2xl border border-gray-200 bg-white py-1 pl-1 pr-3 shadow-sm">
            <div className="grid h-8 w-8 place-items-center rounded-xl bg-brand-500 text-xs font-bold text-white">
              {initials}
            </div>
            <div className="hidden sm:block">
              <p className="text-sm font-semibold leading-4 text-gray-950">{userName}</p>
              <p className="text-xs text-gray-500">{userRole}</p>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}
