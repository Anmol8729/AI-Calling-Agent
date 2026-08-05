import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, FileText, Phone, Mail } from "lucide-react";
import api from "../lib/api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { useLabels } from "../store/clinicStore";

const fmtDuration = (s) => `${Math.floor((s || 0) / 60)}m ${(s || 0) % 60}s`;
const fmtDate = (d) => (d ? new Date(d).toLocaleString() : "—");

const callTone = (s) => {
  const v = (s || "").toLowerCase();
  if (["completed", "active"].includes(v)) return "success";
  if (v === "transferred") return "warning";
  if (["failed", "no-answer", "blocked"].includes(v)) return "danger";
  return "neutral";
};
const apptTone = (s) => {
  switch (s) {
    case "completed": return "success";
    case "cancelled": return "danger";
    case "scheduled": return "warning";
    default: return "neutral";
  }
};

export default function ContactDetail() {
  const { id } = useParams();
  const labels = useLabels();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState(null);

  useEffect(() => {
    api.get(`/patients/${id}/detail`)
      .then((r) => { if (r.data?.success) setData(r.data.data); else setError(r.data?.message || "Not found"); })
      .catch(() => setError("Could not load this contact."))
      .finally(() => setLoading(false));
  }, [id]);

  const contact = data?.contact || {};
  const appts = data?.appointments || [];
  const calls = data?.calls || [];

  const apptColumns = [
    { key: "appointment_at", header: "When", render: (r) => (r.appointment_at ? new Date(r.appointment_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : r.appointment_date || "—") },
    { key: "reason", header: "Reason", render: (r) => r.reason || "—" },
    { key: "status", header: "Status", render: (r) => <Badge tone={apptTone(r.status)}>{r.status}</Badge> },
  ];

  const callColumns = [
    { key: "created_at", header: "When", render: (r) => fmtDate(r.created_at) },
    { key: "direction", header: "Direction", render: (r) => <span className="capitalize">{r.direction || "inbound"}</span> },
    { key: "duration", header: "Duration", render: (r) => fmtDuration(r.duration) },
    { key: "status", header: "Outcome", render: (r) => <Badge tone={callTone(r.status)}>{r.status || "unknown"}</Badge> },
    {
      key: "actions",
      header: "Transcript",
      render: (r) => {
        const t = Array.isArray(r.transcript) ? r.transcript : [];
        return (
          <Button variant="secondary" size="sm" disabled={!t.length} onClick={() => setTranscript(t)}>
            <FileText className="h-3.5 w-3.5" />
          </Button>
        );
      },
    },
  ];

  if (error) {
    return (
      <div className="space-y-4">
        <Link to="/contacts" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-950"><ArrowLeft className="h-4 w-4" /> Back</Link>
        <div className="rounded-2xl border border-red-100 bg-red-50 p-4 text-sm text-red-800">{error}</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link to="/contacts" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-950">
        <ArrowLeft className="h-4 w-4" /> Back to {labels.contacts.toLowerCase()}
      </Link>

      {/* Contact card */}
      <section className="panel rounded-3xl border border-gray-100 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-gray-950">{loading ? "…" : (contact.name || "Contact")}</h1>
            <div className="mt-2 flex flex-wrap gap-4 text-sm text-gray-600">
              <span className="inline-flex items-center gap-1"><Phone className="h-4 w-4 text-gray-400" /> {contact.phone || "—"}</span>
              <span className="inline-flex items-center gap-1"><Mail className="h-4 w-4 text-gray-400" /> {contact.email || "—"}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={(contact.history && contact.history.length > 0) ? "success" : "neutral"}>
              {(contact.history && contact.history.length > 0) ? "Returning" : "New"}
            </Badge>
            <Badge tone={contact.source === "manual" ? "neutral" : "dark"}>
              {contact.source === "manual" ? "Manual" : "Agent"}
            </Badge>
          </div>
        </div>
        {(contact.gender || contact.age || contact.follow_up_notes) && (
          <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
            {(contact.gender || contact.age) && (
              <div><span className="text-gray-500">Details: </span><span className="text-gray-900">{[contact.gender, contact.age ? `Age ${contact.age}` : null].filter(Boolean).join(", ")}</span></div>
            )}
            {contact.follow_up_notes && (
              <div><span className="text-gray-500">Notes: </span><span className="text-gray-900">{contact.follow_up_notes}</span></div>
            )}
          </div>
        )}
      </section>

      {/* Appointments */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-950">{labels.bookings}</h2>
        <DataTable columns={apptColumns} rows={appts} loading={loading} emptyTitle={`No ${labels.bookings.toLowerCase()} yet`} />
      </section>

      {/* Calls */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-gray-950">Calls</h2>
        <DataTable columns={callColumns} rows={calls} loading={loading} emptyTitle="No calls yet" />
      </section>

      <Modal
        open={!!transcript}
        onClose={() => setTranscript(null)}
        title="Call transcript"
        footer={<div className="flex justify-end"><Button onClick={() => setTranscript(null)}>Close</Button></div>}
      >
        {transcript && transcript.length > 0 ? (
          <div className="space-y-3">
            {transcript.map((turn, i) => {
              const isCaller = (turn.role || "").toLowerCase() === "user";
              return (
                <div key={i} className={`flex ${isCaller ? "justify-start" : "justify-end"}`}>
                  <div className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${isCaller ? "bg-gray-100 text-gray-900" : "bg-gray-950 text-white"}`}>
                    <p className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider opacity-60">{isCaller ? "Caller" : "AI Receptionist"}</p>
                    {turn.content}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No transcript.</p>
        )}
      </Modal>
    </div>
  );
}
