import { useEffect, useState } from "react";
import {
  Bot,
  CalendarCheck,
  CreditCard,
  Gauge,
  Headphones,
  MessageCircle,
  Settings,
  ShieldCheck,
  Users,
  UserCog,
  UserRoundCog,
  X,
  LogOut,
} from "lucide-react";
import { NavLink } from "react-router-dom";
import api from "../lib/api";
import { useAuthStore } from "../store/authStore";
import { useLabels } from "../store/clinicStore";

const items = [
  { label: "Dashboard", path: "/dashboard", icon: Gauge },
  { label: "Calls", path: "/calls", icon: Headphones },
  { label: "Contacts", path: "/contacts", icon: Users },
  { label: "Appointments", path: "/appointments", icon: CalendarCheck },
  { label: "Messages", path: "/messages", icon: MessageCircle },
  { label: "Agent Setup", path: "/setup", icon: Settings },
  { label: "Staff", path: "/staff", icon: UserRoundCog },
  { label: "Billing", path: "/billing", icon: CreditCard },
  { label: "Account", path: "/account", icon: UserCog },
];

export default function Sidebar({ open, onClose }) {
  const logout = useAuthStore((state) => state.logout);
  const user = useAuthStore((state) => state.user);
  const labels = useLabels();

  // Real "connected numbers" status (replaces the old hardcoded SIP badge).
  // Refreshes periodically + on window focus so it reflects numbers you connect
  // on the Setup page without needing a full reload.
  const [numbers, setNumbers] = useState(null); // null = loading
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
  const activeNumbers = (numbers || []).filter((n) => n.status === "active").length;

  // Nav labels that adapt to the tenant's industry.
  const labelOverrides = { "/contacts": labels.contacts, "/appointments": labels.bookings };

  // Platform admins get an extra Admin entry (server also enforces access).
  // Staff can only see the core read-only nav items.
  const STAFF_HIDDEN_PATHS = new Set(["/setup", "/staff", "/billing", "/admin"]);
  const navItems = (user?.is_superadmin
    ? [...items, { label: "Admin", path: "/admin", icon: ShieldCheck }]
    : items
  ).filter((item) => !(user?.role === "staff" && STAFF_HIDDEN_PATHS.has(item.path)));

  const handleLogout = async () => {
    // logout() now also revokes the session server-side, so it is async. Await it
    // before closing the drawer; ProtectedRoute redirects once the store clears.
    await logout();
    onClose?.();
  };

  return (
    <>
      <div
        className={`fixed inset-0 z-40 bg-gray-950/35 backdrop-blur-sm transition lg:hidden ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={onClose}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-gray-200 bg-white/90 px-4 py-5 shadow-2xl shadow-gray-950/10 backdrop-blur-xl transition-transform lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-gray-950 text-white shadow-lg shadow-gray-950/20">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-950">Clarivo</p>
              <p className="text-xs text-gray-500">Inbound reception</p>
            </div>
          </div>
          <button className="rounded-xl p-2 text-gray-500 hover:bg-gray-100 lg:hidden" onClick={onClose}>
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="mt-8 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={onClose}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium transition ${
                  isActive
                    ? "bg-gray-950 text-white shadow-lg shadow-gray-950/15"
                    : "text-gray-600 hover:bg-gray-100 hover:text-gray-950"
                }`
              }
            >
              <item.icon className="h-4 w-4" />
              {labelOverrides[item.path] || item.label}
            </NavLink>
          ))}
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium text-red-600 hover:bg-red-50 hover:text-red-700 transition cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            Logout
          </button>
        </nav>

        <div className="mt-auto rounded-3xl border border-gray-200 bg-gray-50 p-4">
          {numbers === null ? (
            <div className="flex items-center gap-2 text-sm text-gray-400">
              <span className="status-dot bg-gray-300" />
              Checking numbers…
            </div>
          ) : totalNumbers > 0 ? (
            <>
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-950">
                <span className={`status-dot ${activeNumbers > 0 ? "bg-emerald-500" : "bg-amber-500"}`} />
                {totalNumbers} number{totalNumbers === 1 ? "" : "s"} connected
              </div>
              <p className="mt-2 text-xs leading-5 text-gray-500">
                {activeNumbers > 0
                  ? `${activeNumbers} active — calls are answered by your AI receptionist.`
                  : "All numbers are inactive. Activate one in Agent Setup to receive calls."}
              </p>
            </>
          ) : (
            <>
              <div className="flex items-center gap-2 text-sm font-semibold text-gray-950">
                <span className="status-dot bg-amber-500" />
                No number connected
              </div>
              <NavLink
                to="/setup"
                onClick={onClose}
                className="mt-2 inline-block text-xs font-medium text-gray-900 hover:underline"
              >
                Connect a number in Agent Setup →
              </NavLink>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
