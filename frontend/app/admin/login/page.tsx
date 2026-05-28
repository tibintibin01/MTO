"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ShieldAlert, User, Lock, ArrowRight } from "lucide-react";
import Image from "next/image";

export default function AdminLogin() {
  const router = useRouter();
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
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const errJson = await res.json();
        throw new Error(errJson.detail || "Authentication failed. Invalid username or password.");
      }
      const data = await res.json();
      sessionStorage.setItem("mto_user", JSON.stringify({
        username: data.username,
        role: data.role,
        refresh_token: data.refresh_token ?? "",
      }));
      router.push("/admin/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen relative overflow-hidden flex flex-col" style={{background:"#0a1628"}}>

      {/* ── Background ── */}
      <div className="absolute inset-0" style={{background:"#0a1628"}}>
        {/* Photo — left half only, very subtle */}
        <div className="absolute left-0 top-0 bottom-0 w-1/2 opacity-30">
          <Image
            src="/municipal-hall.png"
            alt=""
            fill
            className="object-cover object-center"
            priority
          />
          {/* Fade to right */}
          <div className="absolute inset-0" style={{background:"linear-gradient(to right,transparent 30%,#0a1628 100%)"}} />
          {/* Fade to bottom */}
          <div className="absolute inset-0" style={{background:"linear-gradient(to bottom,transparent 60%,#0a1628 100%)"}} />
        </div>
        {/* Overall dark tint */}
        <div className="absolute inset-0" style={{background:"rgba(10,22,40,0.5)"}} />
      </div>

      {/* ── Header ── */}
      <div className="relative z-10 px-8 py-5 flex items-center gap-4">
        <div className="relative w-12 h-12 flex-shrink-0 rounded-full bg-white shadow ring-2 ring-white/20 overflow-hidden">
          <Image src="/dipaculao-logo.png" alt="Dipaculao Logo" fill className="object-contain p-0.5" />
        </div>
        <div>
          <p className="text-white/50 text-xs uppercase tracking-widest">Republic of the Philippines</p>
          <p className="text-white font-black text-lg leading-tight">Bayan ng Dipaculao</p>
          <p className="text-white/50 text-xs">Municipal Treasury Office – Aurora</p>
        </div>
      </div>

      {/* ── Main content ── */}
      <div className="relative z-10 flex-1 flex items-center justify-end px-8 sm:px-16 py-8">

        {/* Login card — right side */}
        <div className="w-full max-w-sm rounded-2xl p-8"
          style={{
            background:"rgba(13,28,58,0.85)",
            backdropFilter:"blur(20px)",
            WebkitBackdropFilter:"blur(20px)",
            border:"1px solid rgba(255,255,255,0.1)",
            boxShadow:"0 24px 64px rgba(0,0,0,0.5)",
          }}>

          {/* Icon */}
          <div className="flex justify-center mb-5">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
              style={{background:"rgba(31,78,120,0.4)", border:"1px solid rgba(74,162,255,0.3)"}}>
              <ShieldAlert className="w-7 h-7" style={{color:"#4ca2ff"}} />
            </div>
          </div>

          {/* Title */}
          <div className="text-center mb-7">
            <h2 className="text-2xl font-black text-white tracking-tight">Municipal Treasury</h2>
            <p className="text-sm mt-1" style={{color:"#4ca2ff"}}>Staff Secure Access Terminal</p>
          </div>

          {/* Error */}
          {error && (
            <div className="rounded-xl p-3 mb-5 text-sm text-red-300 flex gap-2"
              style={{background:"rgba(239,68,68,0.1)", border:"1px solid rgba(239,68,68,0.25)"}}>
              <span>⚠</span> {error}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-xs font-bold uppercase tracking-widest mb-2" style={{color:"#94a3b8"}}>
                Username
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center" style={{color:"#64748b"}}>
                  <User className="w-4 h-4" />
                </span>
                <input
                  type="text"
                  className="w-full pl-10 pr-4 py-3 rounded-xl text-white placeholder-slate-500 outline-none transition-all text-sm"
                  style={{
                    background:"rgba(255,255,255,0.06)",
                    border:"1px solid rgba(255,255,255,0.1)",
                  }}
                  placeholder="Enter username"
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  onFocus={e => e.currentTarget.style.border="1px solid rgba(74,162,255,0.5)"}
                  onBlur={e => e.currentTarget.style.border="1px solid rgba(255,255,255,0.1)"}
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold uppercase tracking-widest mb-2" style={{color:"#94a3b8"}}>
                Password
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center" style={{color:"#64748b"}}>
                  <Lock className="w-4 h-4" />
                </span>
                <input
                  type="password"
                  className="w-full pl-10 pr-4 py-3 rounded-xl text-white placeholder-slate-500 outline-none transition-all text-sm"
                  style={{
                    background:"rgba(255,255,255,0.06)",
                    border:"1px solid rgba(255,255,255,0.1)",
                  }}
                  placeholder="Enter password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  onFocus={e => e.currentTarget.style.border="1px solid rgba(74,162,255,0.5)"}
                  onBlur={e => e.currentTarget.style.border="1px solid rgba(255,255,255,0.1)"}
                  required
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full font-bold py-3 px-6 rounded-xl transition-all flex items-center justify-center gap-2 mt-2 text-sm tracking-widest uppercase disabled:opacity-50"
              style={{background:"#1a5fa8", color:"white"}}
              onMouseEnter={e => !loading && (e.currentTarget.style.background="#2272c3")}
              onMouseLeave={e => (e.currentTarget.style.background="#1a5fa8")}
            >
              {loading ? "Authenticating..." : (
                <>Authenticate Staff <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </form>

          <p className="text-center text-xs mt-6" style={{color:"#475569"}}>
            Authorized personnel access only.<br />Audit tracking active.
          </p>
        </div>
      </div>

      {/* ── Bottom left badge ── */}
      <div className="relative z-10 px-8 pb-6">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{background:"rgba(255,255,255,0.08)", border:"1px solid rgba(255,255,255,0.1)"}}>
            <ShieldAlert className="w-4 h-4" style={{color:"#4ca2ff"}} />
          </div>
          <div>
            <p className="text-white text-xs font-bold">Secure Access</p>
            <p className="text-xs" style={{color:"#475569"}}>This system is for authorized municipal personnel only.</p>
          </div>
        </div>
      </div>

      {/* ── Footer ── */}
      <div className="relative z-10 border-t px-8 py-5 grid grid-cols-1 sm:grid-cols-3 gap-6 items-center"
        style={{borderColor:"rgba(255,255,255,0.08)", background:"rgba(5,12,28,0.85)"}}>

        {/* Col 1 — Logo + name */}
        <div className="flex items-center gap-3">
          <div className="relative w-9 h-9 flex-shrink-0 rounded-full bg-white overflow-hidden ring-1 ring-white/20">
            <Image src="/dipaculao-logo.png" alt="" fill className="object-contain p-0.5" />
          </div>
          <div>
            <p className="text-white text-sm font-bold">Bayan ng Dipaculao</p>
            <p className="text-xs" style={{color:"#475569"}}>Province of Aurora</p>
          </div>
        </div>

        {/* Col 2 — Legal */}
        <div className="flex items-start gap-3">
          <Lock className="w-4 h-4 flex-shrink-0 mt-0.5" style={{color:"#475569"}} />
          <p className="text-xs leading-relaxed" style={{color:"#64748b"}}>
            Data Privacy Act of 2012 (RA 10173)<br />
            and the Local Government Code (RA 7160).
          </p>
        </div>

        {/* Col 3 — Copyright */}
        <div className="flex items-start gap-3 sm:justify-end">
          <p className="text-xs leading-relaxed text-right" style={{color:"#64748b"}}>
            © 2026 Municipal Treasury Office of<br />
            Dipaculao, Aurora. All Rights Reserved.
          </p>
        </div>

      </div>
    </div>
  );
}
