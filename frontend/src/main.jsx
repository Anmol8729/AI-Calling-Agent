import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import ProtectedRoute from "./components/ProtectedRoute";
import SuperadminRoute from "./components/SuperadminRoute";
import ErrorBoundary from "./components/ErrorBoundary";
import ScreenLoader from "./components/ScreenLoader";
// Login stays eager: it's the landing page for anyone not signed in, so lazy
// loading it would only add a round trip before the very first paint.
import Login from "./pages/Login";
import "./styles.css";

// Every other page is code-split. This keeps heavy, page-specific dependencies
// (Recharts on the Dashboard, for example) out of the initial download, so the
// first screen loads fast instead of shipping the whole app up front.
const Register = lazy(() => import("./pages/Register"));
const ForgotPassword = lazy(() => import("./pages/ForgotPassword"));
const AuthCallback = lazy(() => import("./pages/AuthCallback"));
const ResetPassword = lazy(() => import("./pages/ResetPassword"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const Calls = lazy(() => import("./pages/Calls"));
const Contacts = lazy(() => import("./pages/Contacts"));
const ContactDetail = lazy(() => import("./pages/ContactDetail"));
const Appointments = lazy(() => import("./pages/Appointments"));
const Messages = lazy(() => import("./pages/Messages"));
const Setup = lazy(() => import("./pages/Setup"));
const Billing = lazy(() => import("./pages/Billing"));
const Account = lazy(() => import("./pages/Account"));
const Admin = lazy(() => import("./pages/Admin"));

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<ScreenLoader />}>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            {/* Google's redirect target. Must be public: the user has no app
                session yet at this point, so it cannot sit behind ProtectedRoute. */}
            <Route path="/auth/callback" element={<AuthCallback />} />
            <Route
              path="/*"
              element={
                <ProtectedRoute>
                  <Routes>
                    <Route element={<AppLayout />}>
                      <Route index element={<Navigate to="/dashboard" replace />} />
                      <Route path="/dashboard" element={<Dashboard />} />
                      <Route path="/calls" element={<Calls />} />
                      <Route path="/contacts" element={<Contacts />} />
                      <Route path="/contacts/:id" element={<ContactDetail />} />
                      <Route path="/appointments" element={<Appointments />} />
                      <Route path="/messages" element={<Messages />} />
                      <Route path="/setup" element={<Setup />} />
                      <Route path="/billing" element={<Billing />} />
                      <Route path="/account" element={<Account />} />
                      <Route
                        path="/admin"
                        element={
                          <SuperadminRoute>
                            <Admin />
                          </SuperadminRoute>
                        }
                      />

                      {/* Redirects from the old (pre-consolidation) routes */}
                      <Route path="/agents" element={<Navigate to="/setup" replace />} />
                      <Route path="/settings" element={<Navigate to="/setup" replace />} />
                      <Route path="/knowledge-base" element={<Navigate to="/setup" replace />} />
                      <Route path="/phone-numbers" element={<Navigate to="/setup" replace />} />
                      <Route path="/calls/live" element={<Navigate to="/calls" replace />} />
                      <Route path="/call-logs" element={<Navigate to="/calls" replace />} />
                      <Route path="/analytics" element={<Navigate to="/dashboard" replace />} />
                    </Route>
                  </Routes>
                </ProtectedRoute>
              }
            />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
