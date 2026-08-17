import React from "react";
import { Navigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

/**
 * The inverse of ProtectedRoute: for pages that only make sense to a visitor who is
 * NOT signed in.
 *
 * It exists for the landing page. That page is mounted at "/", which is also the URL
 * existing customers have bookmarked for the dashboard — without this, signing in and
 * then typing the bare domain would show them the marketing site instead of their
 * dashboard, which is what happened before the merge.
 */
export default function PublicOnlyRoute({ children, redirectTo = "/dashboard" }) {
  const { isAuthenticated } = useAuthStore();

  if (isAuthenticated) {
    return <Navigate to={redirectTo} replace />;
  }

  return children;
}
