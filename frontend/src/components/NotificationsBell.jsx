import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, CalendarCheck, PhoneCall } from "lucide-react";
import api from "../lib/api";
import { useLabels } from "../store/clinicStore";

function timeAgo(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const mins = Math.floor(Math.max(0, Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function apptItem(x, bookingWord) {
  return {
    id: `a-${x.id}`,
    kind: "appointment",
    title: `New ${bookingWord}: ${x.patient_name || "someone"}`,
    meta: x.appointment_date || "",
    ts: x.created_at,
    to: "/appointments",
  };
}

function callItem(x) {
  return {
    id: `c-${x.call_id || x.id}`,
    kind: "call",
    title: `Call from ${x.caller_name || x.phone || "unknown"}`,
    meta: x.status || "",
    ts: x.created_at,
    to: "/calls",
  };
}

// Build the seeded list from recent appointments + calls (REST).
function buildItems(appts, calls, bookingWord) {
  return [...appts.slice(0, 10).map((x) => apptItem(x, bookingWord)), ...calls.slice(0, 10).map(callItem)]
    .filter((n) => n.ts)
    .sort((p, q) => new Date(q.ts) - new Date(p.ts))
    .slice(0, 8);
}

// Map a live WebSocket event to a list item.
function eventToItem(ev, bookingWord) {
  if (ev.type === "appointment") {
    return {
      id: ev.id || `a-${ev.ts}`,
      kind: "appointment",
      title: `New ${bookingWord}: ${ev.name || "someone"}`,
      meta: ev.meta || "",
      ts: ev.ts,
      to: ev.to || "/appointments",
    };
  }
  return {
    id: ev.id || `c-${ev.ts}`,
    kind: "call",
    title: `Call from ${ev.name || "unknown"}`,
    meta: ev.meta || "",
    ts: ev.ts,
    to: ev.to || "/calls",
  };
}

function fetchActivity() {
  return Promise.all([
    api.get("/appointments/").then((r) => (r.data?.success ? r.data.data || [] : [])).catch(() => []),
    api.get("/calls/logs").then((r) => (r.data?.success ? r.data.data || [] : [])).catch(() => []),
  ]);
}

// Derive the WebSocket URL from the REST base: swap http->ws and
// drop the trailing /api, then add the notifications path + auth token.
function notificationsWsUrl() {
  let base;
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    if (host !== "app.clarivo.net.in" && host !== "clarivo-dashboard-git.pages.dev" && host !== "localhost" && host !== "127.0.0.1") {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      base = `${proto}//${window.location.host}`;
    }
  }
  if (!base) {
    const apiBase = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
    base = apiBase.replace(/^http/i, "ws").replace(/\/api\/?$/i, "");
  }
  const token = localStorage.getItem("token") || "";
  return `${base}/ws/notifications?token=${encodeURIComponent(token)}`;
}

// Notifications come from real activity: recent bookings + calls are seeded over
// REST, and new ones arrive live over a WebSocket (with auto-reconnect). The
// unread badge counts items since the tray was last opened.
export default function NotificationsBell() {
  const labels = useLabels();
  const bookingWord = labels.booking.toLowerCase();
  const bookingWordRef = useRef(bookingWord);
  useEffect(() => {
    bookingWordRef.current = bookingWord;
  }, [bookingWord]);

  const [open, setOpen] = useState(false);
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const ref = useRef(null);
  const lastSeenRef = useRef(Number(localStorage.getItem("notifsSeenAt") || 0));

  // Seed recent history from REST (re-runs if the booking label resolves later).
  useEffect(() => {
    let cancelled = false;
    fetchActivity().then(([appts, calls]) => {
      if (cancelled) return;
      const merged = buildItems(appts, calls, bookingWord);
      setItems(merged);
      setUnread(merged.filter((n) => new Date(n.ts).getTime() > lastSeenRef.current).length);
    });
    return () => {
      cancelled = true;
    };
  }, [bookingWord]);

  // Live stream over a WebSocket, with reconnect. One connection for the app.
  useEffect(() => {
    let ws = null;
    let retry = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      // Skip the WS entirely when unauthenticated or the account has no clinic —
      // the server closes those with code 4401, so connecting would just loop.
      let clinicId = null;
      try {
        clinicId = JSON.parse(localStorage.getItem("user") || "{}")?.clinic_id;
      } catch {
        clinicId = null;
      }
      if (!localStorage.getItem("token") || !clinicId) return;
      try {
        ws = new WebSocket(notificationsWsUrl());
      } catch {
        retry = setTimeout(connect, 4000);
        return;
      }
      ws.onmessage = (e) => {
        let ev;
        try {
          ev = JSON.parse(e.data);
        } catch {
          return;
        }
        if (!ev || !ev.type || ev.type === "connected" || ev.type === "ping") return;
        const item = eventToItem(ev, bookingWordRef.current);
        setItems((prev) => [item, ...prev.filter((p) => p.id !== item.id)].slice(0, 8));
        setUnread((u) => u + 1);
      };
      ws.onclose = (e) => {
        // 4401 = auth rejected (missing/expired token, or no clinic on the
        // account). That's permanent — don't hammer the server with reconnects.
        if (!stopped && e.code !== 4401) retry = setTimeout(connect, 4000);
      };
      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      if (ws) {
        try {
          ws.close();
        } catch {
          /* noop */
        }
      }
    };
  }, []);

  // Close the tray on an outside click.
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next) {
      const now = Date.now();
      lastSeenRef.current = now;
      localStorage.setItem("notifsSeenAt", String(now));
      setUnread(0);
      fetchActivity().then(([appts, calls]) => setItems(buildItems(appts, calls, bookingWordRef.current)));
    }
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={toggle}
        aria-label={unread > 0 ? `Notifications, ${unread} new` : "Notifications"}
        className="relative grid h-10 w-10 place-items-center rounded-xl border border-gray-200 bg-white text-gray-700 shadow-sm transition hover:bg-gray-50"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 grid h-5 min-w-[1.25rem] place-items-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-xl">
          <div className="border-b border-gray-100 px-4 py-3">
            <p className="text-sm font-semibold text-gray-950">Recent activity</p>
          </div>
          {items.length === 0 ? (
            <div className="px-4 py-6 text-center text-sm text-gray-400">No recent activity yet.</div>
          ) : (
            <ul className="max-h-80 divide-y divide-gray-100 overflow-y-auto">
              {items.map((n) => (
                <li key={n.id}>
                  <Link
                    to={n.to}
                    onClick={() => setOpen(false)}
                    className="flex items-start gap-3 px-4 py-3 transition hover:bg-gray-50"
                  >
                    <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gray-100 text-gray-700">
                      {n.kind === "appointment" ? <CalendarCheck className="h-4 w-4" /> : <PhoneCall className="h-4 w-4" />}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-gray-900">{n.title}</span>
                      <span className="block truncate text-xs text-gray-500">
                        {n.meta ? `${n.meta} · ` : ""}
                        {timeAgo(n.ts)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
