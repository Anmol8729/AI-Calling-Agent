import { useEffect } from "react";
import { NavLink, Link } from "react-router-dom";
import { Bot, Menu, Sparkles } from "lucide-react";
import NotificationsBell from "./NotificationsBell";
import { useAuthStore } from "../store/authStore";
import { useClinicStore, useLabels } from "../store/clinicStore";

export default function Navbar({ onMenuClick }) {
  const { user } = useAuthStore();
  const businessName = useClinicStore((s) => s.clinic?.name);
  const fetchClinic = useClinicStore((s) => s.fetchClinic);
  const labels = useLabels();

  useEffect(() => {
    fetchClinic();
  }, [fetchClinic]);

  const userName = user?.name || "Admin";
  const userRole = user?.role
    ? user.role.charAt(0).toUpperCase() + user.role.slice(1)
    : user?.is_superadmin
    ? "SuperAdmin"
    : "Team member";
  const initials =
    userName
      .trim()
      .split(/\s+/)
      .map((word) => word[0])
      .join("")
      .slice(0, 2)
      .toUpperCase() || "C";

  const navLinks = [
    { label: "Dashboard", path: "/dashboard" },
    { label: "Calls", path: "/calls" },
    { label: labels.contacts || "Contacts", path: "/contacts" },
    { label: labels.bookings || "Bookings", path: "/appointments" },
    { label: "Messages", path: "/messages" },
  ];

  return (
    <header className="flex items-center justify-between gap-3 w-full">
      {/* ============================================================== */}
      {/* Left pill: Brand                                               */}
      {/* ============================================================== */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open mobile menu"
          className="lg:hidden h-10 w-10 rounded-full border border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] text-[#0F172A] dark:text-[#F5F7FA] flex items-center justify-center hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] transition-colors"
        >
          <Menu className="h-5 w-5" />
        </button>

        <Link
          to="/dashboard"
          className="h-12 px-4 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-full shadow-[0_1px_2px_rgba(15,23,42,0.03)] flex items-center hover:border-[#007BA7]/40 transition-colors"
          title="Clarivo Home"
        >
          <img
            src="/logo-light.png"
            alt="Clarivo"
            className="h-7 w-auto object-contain dark:hidden"
          />
          <img
            src="/logo-dark.png"
            alt="Clarivo"
            className="h-7 w-auto object-contain hidden dark:block"
          />
        </Link>
      </div>

      {/* ============================================================== */}
      {/* Centre pill navigation (5 items)                               */}
      {/* ============================================================== */}
      <nav className="hidden md:flex h-12 px-1.5 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-full shadow-[0_1px_2px_rgba(15,23,42,0.03)] items-center gap-1">
        {navLinks.map((link) => (
          <NavLink
            key={link.path}
            to={link.path}
            className={({ isActive }) =>
              `px-3.5 py-1.5 rounded-full font-medium text-[13px] transition-colors ${
                isActive
                  ? "bg-[#007BA7] text-white shadow-sm"
                  : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D]"
              }`
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>

      {/* ============================================================== */}
      {/* Right controls: Status, Notifications, User Profile            */}
      {/* ============================================================== */}
      <div className="flex items-center gap-2">
        {/* System online pill */}
        <div className="hidden sm:flex h-10 px-3 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-full items-center gap-2 text-[12px] font-medium text-[#0F172A] dark:text-[#F5F7FA] shadow-[0_1px_2px_rgba(15,23,42,0.02)]">
          <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
          <span>System online</span>
        </div>

        {/* Notifications */}
        <NotificationsBell />

        {/* User profile pill */}
        <NavLink
          to="/account"
          className="h-10 pl-1 pr-3 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-full flex items-center gap-2 cursor-pointer hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] transition-colors shadow-[0_1px_2px_rgba(15,23,42,0.02)]"
        >
          <div className="w-8 h-8 rounded-full bg-[#007BA7] text-white flex items-center justify-center font-semibold text-[13px]">
            {initials}
          </div>
          <div className="hidden sm:flex flex-col text-left leading-tight">
            <span className="text-[12px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] max-w-[130px] truncate">
              {userName}
            </span>
            <span className="text-[10.5px] text-[#64748B] dark:text-[#A1A1AA] max-w-[130px] truncate">
              {userRole}
            </span>
          </div>
        </NavLink>
      </div>
    </header>
  );
}
