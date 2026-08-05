import React from "react";
import { Navigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

// Blocks staff-role users from reaching routes they are not permitted to use.
// Staff can only view contacts/appointments/calls — they cannot access billing,
// agent setup, or admin pages. The backend still enforces access via
// require_non_staff / require_roles — this only keeps the UI honest.
export default function StaffRoute({ children }) {
  const { user } = useAuthStore();

  if (user?.role === "staff") {
    return <Navigate to="/contacts" replace />;
  }

  return children;
}
