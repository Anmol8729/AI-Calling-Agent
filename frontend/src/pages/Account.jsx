import { useEffect, useState } from "react";
import { Save, KeyRound, UserCog, UserPlus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { Button } from "../components/ui/Button";
import { useAuthStore } from "../store/authStore";

function extractError(err) {
  const d = err?.response?.data;
  if (d?.message) return d.message;
  if (typeof d?.error === "string" && d.error) return d.error;
  if (d?.detail) {
    if (Array.isArray(d.detail)) return d.detail.map((x) => `${x.loc?.[x.loc.length - 1]}: ${x.msg}`).join(", ");
    return d.detail;
  }
  return "Could not reach the server.";
}

function Banner({ msg }) {
  if (!msg) return null;
  return (
    <div className={`rounded-2xl border p-3 text-sm ${msg.type === "success" ? "border-emerald-100 bg-emerald-50 text-emerald-800" : "border-red-100 bg-red-50 text-red-800"}`}>
      {msg.text}
    </div>
  );
}

export default function Account() {
  const navigate = useNavigate();
  // Adopt the replacement token the server issues after a password change.
  const setToken = useAuthStore((state) => state.setToken);
  // Only an owner/doctor sees the staff management section.
  const user = useAuthStore((state) => state.user);
  const isDoctor = user?.role === "doctor";

  const [profile, setProfile] = useState({ email: "", role: "" });
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPwd, setSavingPwd] = useState(false);
  const [pwdMsg, setPwdMsg] = useState(null);

  useEffect(() => {
    api.get("/auth/me")
      .then((res) => {
        if (res.data?.success) {
          const d = res.data.data;
          setProfile({ email: d.email || "", role: d.role || "" });
          setName(d.name || "");
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const saveProfile = async () => {
    setProfileMsg(null);
    if (!name.trim()) {
      setProfileMsg({ type: "error", text: "Name is required." });
      return;
    }
    setSavingProfile(true);
    try {
      const res = await api.put("/auth/profile", { name: name.trim() });
      setProfileMsg(res.data?.success
        ? { type: "success", text: "Profile updated." }
        : { type: "error", text: res.data?.message || "Could not update profile." });
    } catch (err) {
      setProfileMsg({ type: "error", text: extractError(err) });
    } finally {
      setSavingProfile(false);
    }
  };

  const changePassword = async () => {
    setPwdMsg(null);
    if (newPassword.length < 6) {
      setPwdMsg({ type: "error", text: "New password must be at least 6 characters." });
      return;
    }
    if (newPassword !== confirmPassword) {
      setPwdMsg({ type: "error", text: "New passwords don't match." });
      return;
    }
    setSavingPwd(true);
    try {
      const res = await api.post("/auth/change-password", { current_password: currentPassword, new_password: newPassword });
      if (res.data?.success) {
        // Changing the password revokes every existing session server-side,
        // including this tab's. The response carries a freshly issued token, so
        // store it — without this the next request 401s and bounces to /login.
        const fresh = res.data?.data?.access_token;
        if (fresh) setToken(fresh);
        setPwdMsg({
          type: "success",
          text: "Password changed. You've been signed out on all other devices.",
        });
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
      } else {
        setPwdMsg({ type: "error", text: res.data?.message || "Could not change password." });
      }
    } catch (err) {
      setPwdMsg({ type: "error", text: extractError(err) });
    } finally {
      setSavingPwd(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight text-gray-950">Account</h1>
        <p className="mt-2 text-sm text-gray-500">Manage your profile and password.</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <section className="panel rounded-3xl p-6 space-y-4 border border-gray-100 bg-white shadow-sm">
          <div className="flex items-center gap-2 border-b border-gray-100 pb-3">
            <UserCog className="h-5 w-5 text-gray-500" />
            <h2 className="text-lg font-semibold text-gray-950">Profile</h2>
          </div>
          <Banner msg={profileMsg} />
          <div className="space-y-3">
            <Labeled label="Name">
              <input className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none" value={name} onChange={(e) => setName(e.target.value)} disabled={loading} />
            </Labeled>
            <Labeled label="Email">
              <input className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none bg-gray-50 text-gray-500" value={profile.email} disabled readOnly />
            </Labeled>
            <Labeled label="Role">
              <input className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none bg-gray-50 text-gray-500 capitalize" value={profile.role} disabled readOnly />
            </Labeled>
          </div>
          <div className="flex justify-end">
            <Button onClick={saveProfile} disabled={loading || savingProfile}>
              <Save className="h-4 w-4" /> {savingProfile ? "Saving..." : "Save profile"}
            </Button>
          </div>
        </section>

        <section className="panel rounded-3xl p-6 space-y-4 border border-gray-100 bg-white shadow-sm">
          <div className="flex items-center gap-2 border-b border-gray-100 pb-3">
            <KeyRound className="h-5 w-5 text-gray-500" />
            <h2 className="text-lg font-semibold text-gray-950">Change password</h2>
          </div>
          <Banner msg={pwdMsg} />
          <div className="space-y-3">
            <Labeled label="Current password">
              <input type="password" className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
            </Labeled>
            <Labeled label="New password">
              <input type="password" className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </Labeled>
            <Labeled label="Confirm new password">
              <input type="password" className="w-full rounded-xl border border-gray-200 px-3.5 py-2 text-sm focus:border-gray-950 focus:outline-none" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
            </Labeled>
          </div>
          <div className="flex justify-end">
            <Button onClick={changePassword} disabled={savingPwd}>
              <KeyRound className="h-4 w-4" /> {savingPwd ? "Updating..." : "Update password"}
            </Button>
          </div>
        </section>
      </div>

      {/* Staff management used to be a form bolted onto the bottom of this page.
          It now lives on its own /staff screen, which also lists existing staff and
          can suspend or remove them — this page is about your own account. */}
      {isDoctor && (
        <section className="panel flex flex-col gap-3 rounded-3xl border border-gray-100 bg-white p-6 shadow-sm sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-start gap-2">
            <UserPlus className="mt-0.5 h-5 w-5 text-gray-500" />
            <div>
              <h2 className="text-lg font-semibold text-gray-950">Staff</h2>
              <p className="text-sm text-gray-500">
                Add a receptionist, suspend someone who has left, or remove an account.
              </p>
            </div>
          </div>
          <Button variant="secondary" onClick={() => navigate("/staff")}>
            Manage staff
          </Button>
        </section>
      )}
    </div>
  );
}

function Labeled({ label, children }) {
  return (
    <div>
      <label className="block text-xs font-semibold uppercase tracking-wider text-gray-500">{label}</label>
      <div className="mt-1">{children}</div>
    </div>
  );
}
