"use client";

import { useState } from "react";
import { ShieldAlert, User, Lock, ArrowRight } from "lucide-react";

export default function AdminLogin() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const res = await fetch("/api/v1/api/auth/login", {
        method: "POST",
        headers: { 
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({ username, password }),
      });


      if (!res.ok) {
        const errJson = await res.json();
        throw new Error(errJson.detail || "Authentication failed. Invalid username or password.");
      }

      const data = await res.json();
      
      // Save credentials in localStorage
      localStorage.setItem("mto_token", data.access_token);
      localStorage.setItem("mto_user", JSON.stringify({ username: data.username, role: data.role }));

      // Redirect to admin dashboard
      window.location.href = "/admin/dashboard";
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-4 relative overflow-hidden font-sans">
      {/* Background elements */}
      <div className="absolute top-[-20%] left-[-20%] w-[60%] h-[60%] bg-blue-900/20 rounded-full blur-[120px] pointer-events-none"></div>
      <div className="absolute bottom-[-20%] right-[-20%] w-[60%] h-[60%] bg-indigo-900/20 rounded-full blur-[120px] pointer-events-none"></div>

      <div className="max-w-md w-full bg-slate-800/60 backdrop-blur-xl border border-slate-700/50 rounded-2xl p-8 shadow-2xl relative z-10">
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-[#1f4e78]/20 border border-[#2c6ea1]/40 text-[#4ca2ff] rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-inner">
            <ShieldAlert className="w-8 h-8" />
          </div>
          <h2 className="text-2xl font-black text-white tracking-tight">Municipal Treasury</h2>
          <p className="text-slate-400 text-sm mt-1">Staff Secure Access Terminal</p>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex gap-3 mb-6 text-sm text-red-300">
            <span className="font-bold flex-1">{error}</span>
          </div>
        )}

        <form onSubmit={handleLogin} className="space-y-6">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Username</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-500">
                <User className="w-5 h-5" />
              </span>
              <input
                type="text"
                className="w-full pl-10 pr-4 py-3 bg-slate-900/60 border border-slate-700/80 rounded-xl text-white placeholder-slate-500 focus:ring-2 focus:ring-[#1f4e78] focus:border-transparent outline-none transition-all"
                placeholder="Enter username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Password</label>
            <div className="relative">
              <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-500">
                <Lock className="w-5 h-5" />
              </span>
              <input
                type="password"
                className="w-full pl-10 pr-4 py-3 bg-slate-900/60 border border-slate-700/80 rounded-xl text-white placeholder-slate-500 focus:ring-2 focus:ring-[#1f4e78] focus:border-transparent outline-none transition-all"
                placeholder="Enter password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#1f4e78] hover:bg-[#2c6ea1] disabled:opacity-50 text-white font-bold py-3 px-6 rounded-xl transition-all flex items-center justify-center gap-2 shadow-lg shadow-[#1f4e78]/30 group"
          >
            {loading ? "AUTHENTICATING..." : (
              <>
                AUTHENTICATE STAFF <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </button>
        </form>

        <div className="text-center mt-8 pt-6 border-t border-slate-700/50">
          <p className="text-xs text-slate-500">Authorized personnel access only. Audit tracking active.</p>
        </div>
      </div>
    </div>
  );
}
