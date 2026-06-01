"use client";

import { useEffect, useState } from "react";
import { 
  Users, 
  Plus, 
  Trash2, 
  Key, 
  AlertCircle,
  CheckCircle2,
  X,
  UserCheck,
  UserPlus
} from "lucide-react";

export default function AdminUsers() {
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  
  // Create Modal
  const [showModal, setShowModal] = useState(false);
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("cashier");

  const fetchUsers = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/v1/users", {
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });

      if (!res.ok) throw new Error("Failed to load user list.");
      const json = await res.json();
      setUsers(Array.isArray(json) ? json : []);
    } catch (err: any) {
      setError(err.message);
      setUsers([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    try {
      const res = await fetch("/api/v1/users", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          username,
          full_name: fullName,
          password,
          role,
          is_active: true
        })
      });

      if (!res.ok) {
        const errJson = await res.json();
        throw new Error(errJson.detail || "Failed to create user account.");
      }

      setSuccess(`User account "${username}" successfully registered!`);
      setShowModal(false);
      setUsername("");
      setFullName("");
      setPassword("");
      setRole("cashier");
      fetchUsers();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleToggleActive = async (userId: number, currentStatus: boolean) => {
    setError("");
    setSuccess("");
    try {
      const res = await fetch(`/api/v1/users/${userId}`, {
        method: "PATCH",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({ is_active: !currentStatus })
      });

      if (!res.ok) throw new Error("Failed to modify account status.");
      fetchUsers();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteUser = async (userId: number, name: string) => {
    if (!confirm(`CRITICAL CONFIRMATION: Are you sure you want to permanently delete the user account "${name}"?`)) return;
    setError("");
    setSuccess("");
    try {
      const res = await fetch(`/api/v1/users/${userId}`, {
        method: "DELETE",
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });

      if (!res.ok) throw new Error("Failed to delete user account.");
      setSuccess(`User "${name}" has been deleted from the registry!`);
      fetchUsers();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleResetPassword = async (userId: number, name: string) => {
    const newPass = prompt(`Enter a new secure password for "${name}":`);
    if (!newPass) return;
    if (newPass.length < 6) {
      alert("Password must be at least 6 characters long.");
      return;
    }

    setError("");
    setSuccess("");
    try {
      const res = await fetch(`/api/v1/users/${userId}/reset-password`, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({ new_password: newPass })
      });

      if (!res.ok) throw new Error("Failed to reset password.");
      setSuccess(`Password for user "${name}" successfully updated!`);
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Access Control</p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Staff Management</h1>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center justify-center gap-2 px-5 py-3 bg-[#1f4e78] hover:bg-[#2c6ea1] text-white font-bold text-sm uppercase tracking-wider rounded-xl transition-all shadow-lg shadow-[#1f4e78]/25"
        >
          <Plus className="w-5 h-5" /> Add Staff Member
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 flex gap-3 text-sm text-red-300">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span className="font-bold flex-1">{error}</span>
        </div>
      )}

      {success && (
        <div className="bg-green-500/10 border border-green-500/25 rounded-2xl p-4 flex gap-3 text-sm text-green-300">
          <CheckCircle2 className="w-5 h-5 shrink-0" />
          <span className="font-bold flex-1">{success}</span>
        </div>
      )}

      {/* Users table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl shadow-black/15">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-slate-950/60 border-b border-slate-800 text-slate-400 font-extrabold text-xs uppercase tracking-wider">
                <th className="px-6 py-4 font-extrabold">Username</th>
                <th className="px-6 py-4 font-extrabold">Full Name</th>
                <th className="px-6 py-4 font-extrabold">Assigned Role</th>
                <th className="px-6 py-4 font-extrabold text-center">Status</th>
                <th className="px-6 py-4 font-extrabold text-center w-48">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {users.length > 0 ? (
                users.map((u, i) => (
                  <tr key={i} className="hover:bg-slate-850/40 transition-colors">
                    <td className="px-6 py-4 font-bold text-white flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full bg-blue-500"></div>
                      {u.username}
                    </td>
                    <td className="px-6 py-4 text-slate-350 font-semibold">{u.full_name}</td>
                    <td className="px-6 py-4">
                      <span className="text-[10px] font-extrabold text-indigo-400 bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 rounded-full uppercase">
                        {u.role}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-center">
                      <button
                        onClick={() => handleToggleActive(u.id, u.is_active)}
                        className={`text-[10px] font-extrabold px-3 py-1 rounded-full uppercase border transition-all ${
                          u.is_active 
                            ? 'text-green-400 bg-green-500/10 border-green-500/20 hover:bg-green-500/20' 
                            : 'text-slate-400 bg-slate-500/10 border-slate-500/20 hover:bg-slate-500/20'
                        }`}
                      >
                        {u.is_active ? "Active" : "Disabled"}
                      </button>
                    </td>
                    <td className="px-6 py-4 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <button
                          onClick={() => handleResetPassword(u.id, u.username)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-850 hover:bg-slate-800 border border-slate-750 text-slate-300 hover:text-white rounded-lg transition-colors text-xs font-bold"
                        >
                          <Key className="w-3.5 h-3.5" />
                          Key
                        </button>
                        <button
                          onClick={() => handleDeleteUser(u.id, u.username)}
                          className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg border border-red-500/20 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="py-20 text-center text-slate-500 font-bold">
                    No staff accounts found in registry.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add User Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden animate-zoom-in">
            <div className="px-6 py-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
              <h3 className="font-bold text-base text-white uppercase tracking-wider flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-[#4ca2ff]" />
                Register Staff Member
              </h3>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-6 h-6" />
              </button>
            </div>

            <form onSubmit={handleCreateUser} className="p-6 space-y-5">
              <div>
                <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Username</label>
                <input
                  type="text"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                  placeholder="e.g. jdoe"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Full Name</label>
                <input
                  type="text"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                  placeholder="e.g. John Doe"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  required
                />
              </div>

              <div>
                <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Access Role</label>
                <select
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="cashier">Cashier</option>
                  <option value="viewer">Viewer</option>
                  <option value="admin">Administrator</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Initial Password</label>
                <input
                  type="password"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              <div className="pt-4 border-t border-slate-800 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="bg-slate-800 hover:bg-slate-750 text-slate-350 px-5 py-3 rounded-xl font-bold text-xs uppercase tracking-wider border border-slate-750 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="bg-[#1f4e78] hover:bg-[#2c6ea1] text-white px-6 py-3 rounded-xl font-bold text-xs uppercase tracking-wider transition-colors animate-pulse"
                >
                  Register Account
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
