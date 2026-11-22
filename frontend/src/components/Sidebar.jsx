import { useEffect, useState } from "react";
import {
  Bot,
  CalendarCheck,
  ChevronRight,
  CreditCard,
  LayoutDashboard,
  Headphones,
  MessageCircle,
  Sliders,
  ShieldCheck,
  Users,
  UserRoundCog,
  User,
  X,
  LogOut,
  PhoneCall,
  Sun,
  Moon,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import api from "../lib/api";
import { useAuthStore } from "../store/authStore";
import { useClinicStore, useLabels } from "../store/clinicStore";
import { useThemeStore } from "../store/themeStore";

const items = [
  { label: "Dashboard", path: "/dashboard", icon: LayoutDashboard },
  { label: "Calls", path: "/calls", icon: Headphones },
  { label: "Contacts", path: "/contacts", icon: Users },
  { label: "Appointments", path: "/appointments", icon: CalendarCheck },
  { label: "Messages", path: "/messages", icon: MessageCircle },
  { label: "Agent Setup", path: "/setup", icon: Sliders },
  { label: "Staff", path: "/staff", icon: UserRoundCog },
  { label: "Billing", path: "/billing", icon: CreditCard },
  { label: "Account", path: "/account", icon: User },
];

export default function Sidebar({ open, onClose }) {
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);
  const labels = useLabels();
  const { theme, toggleTheme } = useThemeStore();

  const [numbers, setNumbers] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api
        .get("/phone-numbers/")
        .then((r) => {
          if (!cancelled) setNumbers(r.data?.success ? r.data.data || [] : []);
        })
        .catch(() => {
          if (!cancelled) setNumbers([]);
        });
    };
    load();
    const id = setInterval(load, 45000);
    window.addEventListener("focus", load);
    return () => {
      cancelled = true;
      clearInterval(id);
      window.removeEventListener("focus", load);
    };
  }, []);

  const totalNumbers = (numbers || []).length;
  const activeNumbers = (numbers || []).filter(
    (n) => n.status === "active" && n.verification_status === "verified"
  ).length;

  const labelOverrides = { "/contacts": labels.contacts, "/appointments": labels.bookings };
  const STAFF_HIDDEN_PATHS = new Set(["/setup", "/staff", "/billing", "/admin"]);
  const navItems = (user?.is_superadmin
    ? [...items, { label: "Admin", path: "/admin", icon: ShieldCheck }]
    : items
  ).filter((item) => !(user?.role === "staff" && STAFF_HIDDEN_PATHS.has(item.path)));

  const handleLogout = async () => {
    await logout();
    onClose?.();
  };

  return (
    <>
      {/* ============================================================== */}
      {/* 1. DESKTOP FLOATING ICON RAIL (56px / w-14)                     */}
      {/* ============================================================== */}
      <aside className="hidden lg:flex w-14 flex-shrink-0 flex-col gap-3 sticky top-4 z-20">
        {/* Top panel: Theme toggle */}
        <div className="w-14 p-1.5 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-[22px] flex flex-col items-center shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
          <button
            type="button"
            onClick={toggleTheme}
            title={theme === "dark" ? "Switch to Light mode" : "Switch to Dark mode"}
            className="w-10 h-10 rounded-full flex items-center justify-center transition-colors text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] cursor-pointer"
          >
            {theme === "dark" ? (
              <Sun className="h-[19px] w-[19px] text-[#007BA7]" />
            ) : (
              <Moon className="h-[19px] w-[19px] text-[#007BA7]" />
            )}
          </button>
        </div>

        {/* Middle panel: 10 Navigation icons */}
        <div className="w-14 py-2 px-1.5 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-[22px] flex flex-col items-center gap-1 shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
          {navItems.map((item) => {
            const Icon = item.icon;
            const displayLabel = labelOverrides[item.path] || item.label;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                title={displayLabel}
                className={({ isActive }) =>
                  `group relative w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
                    isActive
                      ? "bg-[#007BA7] text-white shadow-sm"
                      : "text-[#64748B] dark:text-[#A1A1AA] hover:text-[#0F172A] dark:hover:text-[#F5F7FA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D]"
                  }`
                }
              >
                <Icon className="h-5 w-5" />
                {/* Floating tooltip */}
                <div className="absolute left-12 ml-2 px-2.5 py-1 bg-[#0F172A] text-white text-[11.5px] font-medium rounded-lg whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50 shadow-md">
                  {displayLabel}
                </div>
              </NavLink>
            );
          })}
        </div>

        {/* Bottom panel: Phone status & logout */}
        <div className="w-14 p-1.5 bg-white dark:bg-[#111315] border border-[#E4E8EE] dark:border-[#252A30] rounded-[22px] flex flex-col items-center gap-1 shadow-[0_1px_3px_rgba(15,23,42,0.03)]">
          <NavLink
            to="/setup"
            title="Connected numbers"
            className="group relative w-10 h-10 rounded-full text-[#0F172A] dark:text-[#F5F7FA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] flex items-center justify-center transition-colors"
          >
            <PhoneCall className="h-[19px] w-[19px] text-[#64748B] dark:text-[#A1A1AA]" />
            <span
              className={`absolute top-2 right-2 w-2 h-2 rounded-full ring-2 ring-white dark:ring-[#111315] ${
                activeNumbers > 0 ? "bg-[#22C55E]" : "bg-[#F59E0B]"
              }`}
            />
            <div className="absolute left-12 ml-2 px-2.5 py-1 bg-[#0F172A] text-white text-[11px] font-medium rounded-lg whitespace-nowrap opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity z-50 shadow-md">
              {totalNumbers > 0
                ? `${totalNumbers} number${totalNumbers === 1 ? "" : "s"} connected · Manage`
                : "No number connected · Setup"}
            </div>
          </NavLink>
          <button
            type="button"
            onClick={handleLogout}
            title="Logout"
            className="w-10 h-10 rounded-full text-[#64748B] dark:text-[#A1A1AA] hover:text-[#EF4444] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] flex items-center justify-center transition-colors cursor-pointer"
          >
            <LogOut className="h-[19px] w-[19px]" />
          </button>
        </div>
      </aside>

      {/* ============================================================== */}
      {/* 2. MOBILE DRAWER (For small screens)                          */}
      {/* ============================================================== */}
      <div
        className={`fixed inset-0 z-40 bg-black/40 backdrop-blur-sm transition-opacity lg:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] px-4 py-5 shadow-2xl transition-transform lg:hidden ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <img
              src="/logo-light.png"
              alt="Clarivo"
              className="h-8 w-auto object-contain dark:hidden"
            />
            <img
              src="/logo-dark.png"
              alt="Clarivo"
              className="h-8 w-auto object-contain hidden dark:block"
            />
          </div>
          <button
            className="rounded-full p-2 text-[#64748B] dark:text-[#A1A1AA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D]"
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Theme toggle in mobile drawer */}
        <div className="mt-4 px-2">
          <button
            type="button"
            onClick={toggleTheme}
            className="w-full flex items-center justify-between px-3 py-2 rounded-xl bg-[#F5F7FA] dark:bg-[#171A1D] text-xs font-medium text-[#0F172A] dark:text-[#F5F7FA]"
          >
            <span className="flex items-center gap-2">
              {theme === "dark" ? <Sun className="h-4 w-4 text-[#007BA7]" /> : <Moon className="h-4 w-4 text-[#007BA7]" />}
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </span>
            <span className="text-[11px] text-[#64748B] capitalize">{theme}</span>
          </button>
        </div>

        <nav className="mt-6 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const displayLabel = labelOverrides[item.path] || item.label;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-full px-3.5 py-2 text-sm font-medium transition ${
                    isActive
                      ? "bg-[#007BA7] text-white shadow-sm"
                      : "text-[#64748B] dark:text-[#A1A1AA] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] hover:text-[#0F172A] dark:hover:text-[#F5F7FA]"
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                {displayLabel}
              </NavLink>
            );
          })}
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-full px-3.5 py-2 text-sm font-medium text-[#EF4444] hover:bg-[#F5F7FA] dark:hover:bg-[#171A1D] transition cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            Logout
          </button>
        </nav>

        <div className="mt-auto rounded-[18px] border border-[#E4E8EE] dark:border-[#252A30] bg-[#F5F7FA] dark:bg-[#171A1D] p-3.5">
          <div className="flex items-center gap-2 text-xs font-semibold text-[#0F172A] dark:text-[#F5F7FA]">
            <span className={`w-2 h-2 rounded-full ${activeNumbers > 0 ? "bg-[#22C55E]" : "bg-[#F59E0B]"}`} />
            {totalNumbers > 0
              ? `${totalNumbers} number${totalNumbers === 1 ? "" : "s"} connected`
              : "No number connected"}
          </div>
          <NavLink
            to="/setup"
            onClick={onClose}
            className="mt-2.5 flex items-center justify-between rounded-full border border-[#E4E8EE] dark:border-[#252A30] bg-white dark:bg-[#111315] px-3 py-1.5 text-[11px] font-medium text-[#0F172A] dark:text-[#F5F7FA] hover:bg-[#F5F7FA]"
          >
            Manage numbers
            <ChevronRight className="h-3 w-3 text-[#64748B]" />
          </NavLink>
        </div>
      </aside>
    </>
  );
}
