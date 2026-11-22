import { useCallback, useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import api from "../lib/api";
import DataTable from "../components/DataTable";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";

const kindTone = (k) => ((k || "").toLowerCase() === "reminder" ? "warning" : "info");
const statusTone = (s) => ((s || "").toLowerCase() === "sent" ? "success" : "danger");

export default function Messages() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(() => {
    setRefreshing(true);
    api
      .get("/messages/whatsapp")
      .then((r) => setRows(r.data?.success ? r.data.data || [] : []))
      .catch(() => setRows([]))
      .finally(() => setRefreshing(false));
  }, []);

  useEffect(() => {
    api
      .get("/messages/whatsapp")
      .then((r) => setRows(r.data?.success ? r.data.data || [] : []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, []);

  const columns = [
    {
      key: "created_at",
      header: "When",
      render: (r) => (r.created_at ? new Date(r.created_at).toLocaleString() : "—"),
    },
    { key: "to_phone", header: "Recipient", render: (r) => r.to_phone || "—" },
    { key: "kind", header: "Type", render: (r) => <Badge tone={kindTone(r.kind)}>{r.kind || "Notification"}</Badge> },
    { key: "body", header: "Message Content", render: (r) => <span className="max-w-md truncate block">{r.body || "—"}</span> },
    { key: "status", header: "Status", render: (r) => <Badge tone={statusTone(r.status)}>{r.status || "Pending"}</Badge> },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-1 py-0.5">
        <div>
          <h1 className="text-[26px] font-semibold text-[#0F172A] dark:text-[#F5F7FA] tracking-tight leading-tight">
            Messages
          </h1>
          <p className="text-[13.5px] text-[#475569] dark:text-[#A1A1AA] mt-0.5">
            WhatsApp confirmations and reminders sent to your customers.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" onClick={refresh} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
          </Button>
        </div>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        emptyTitle="No WhatsApp messages sent yet"
        emptyDescription="New records will appear here automatically as appointment confirmations and follow-ups are dispatched."
      />
    </div>
  );
}
