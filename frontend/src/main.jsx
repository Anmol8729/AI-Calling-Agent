import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import ProtectedRoute from "./components/ProtectedRoute";
import SuperadminRoute from "./components/SuperadminRoute";
import StaffRoute from "./components/StaffRoute";
import ErrorBoundary from "./components/ErrorBoundary";
import Login from "./pages/Login";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import ResetPassword from "./pages/ResetPassword";
import Landing from "./pages/Landing";
import Account from "./pages/Account";
import Admin from "./pages/Admin";
import Appointments from "./pages/Appointments";
import Billing from "./pages/Billing";
import Calls from "./pages/Calls";
import Contacts from "./pages/Contacts";
import ContactDetail from "./pages/ContactDetail";
import Dashboard from "./pages/Dashboard";
import Messages from "./pages/Messages";
import Setup from "./pages/Setup";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/" element={<Landing />} />
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
                  <Route
                    path="/setup"
                    element={
                      <StaffRoute>
                        <Setup />
                      </StaffRoute>
                    }
                  />
                  <Route
                    path="/billing"
                    element={
                      <StaffRoute>
                        <Billing />
                      </StaffRoute>
                    }
                  />
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
    </BrowserRouter>
    </ErrorBoundary>
  </React.StrictMode>,
);
