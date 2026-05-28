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
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const errJson = await res.json();
        throw new Error(errJson.detail || "Authentication failed.");
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
    <div className="min-h-screen flex flex-col" style={{background:"#080f1e"}}>

      {/* ── MAIN AREA (fills screen minus footer) ── */}
      <div className="flex-1 relative flex flex-col">

        {/* Full background photo — left ~60%, fades right */}
        <div className="absolute inset-0 overflow-hidden">
          <div className="absolute left-0 top-0 bottom-0 w-[65%]">
            <Image
              src="/municipal-hall.png"
              alt="Dipaculao Municipal Hall"
              fill
              className="object-cover object-center"
              style={{filter:"grayscale(60%) brightness(0.35) blur(1px)"}}
              priority
            />
            {/* Fade right edge into dark */}
            <div className="absolute inset-0"
              style={{background:"linear-gradient(to right,transparent 40%,#080f1e 100%)"}} />
            {/* Slight overall darkening */}
            <div className="absolute inset-0" style={{background:"rgba(8,15,30,0.35)"}} />
          </div>
          {/* Right side solid dark */}
          <div className="absolute right-0 top-0 bottom-0 w-[40%]" style={{background:"#080f1e"}} />
        </div>

        {/* ── Header — top left ── */}
        <div className="relative z-10 flex items-center gap-4 px-8 pt-6 pb-4">
          <div className="relative w-12 h-12 flex-shrink-0 rounded-full bg-white shadow-lg ring-2 ring-white/20 overflow-hidden">
            <Image src="/dipaculao-logo.png" alt="Dipaculao" fill className="object-contain p-0.5" />
          </div>
          <div>
            <p className="text-white/40 text-xs uppercase tracking-widest">Republic of the Philippines</p>
            <p className="text-white font-black text-lg leading-tight">Bayan ng Dipaculao</p>
            <p className="text-white/40 text-xs">Municipal Treasury Office – Aurora</p>
          </div>
        </div>

        {/* ── Two-column layout ── */}
        <div className="relative z-10 flex-1 grid grid-cols-1 lg:grid-cols-2 gap-0">

          {/* Left — empty (photo shows through) */}
          <div className="hidden lg:block" />

          {/* Right — login card, vertically centered */}
          <div className="flex items-center justify-center px-8 py-8">
            <div className="w-full max-w-sm">
              <div className="rounded-2xl p-8"
                style={{
                  background:"rgba(13,24,50,0.92)",
                  backdropFilter:"blur(16px)",
                  WebkitBackdropFilter:"blur(16px)",
                  border:"1px solid rgba(255,255,255,0.08)",
                  boxShadow:"0 32px 80px rgba(0,0,0,0.6)",
                }}>

                {/* Shield icon */}
                <div className="flex justify-center mb-5">
                  <div className="w-14 h-14 rounded-2xl flex items-center justify-center"
                    style={{background:"rgba(26,78,140,0.5)", border:"1px solid rgba(74,162,255,0.3)"}}>
                    <ShieldAlert className="w-7 h-7" style={{color:"#4ca2ff"}} />
                  </div>
                </div>

                {/* Title */}
                <div className="text-center mb-7">
                  <h2 className="text-2xl font-black text-white">Municipal Treasury</h2>
                  <p className="text-sm mt-1" style={{color:"#4ca2ff"}}>Staff Secure Access Terminal</p>
                </div>

                {/* Error */}
                {error && (
                  <div className="rounded-xl p-3 mb-5 text-sm text-red-300 flex gap-2"
                    style={{background:"rgba(239,68,68,0.1)", border:"1px solid rgba(239,68,68,0.2)"}}>
                    <span>⚠</span> {error}
                  </div>
                )}

                {/* Form */}
                <form onSubmit={handleLogin} className="space-y-4">
                  <div>
                    <label className="block text-xs font-bold uppercase tracking-widest mb-2"
                      style={{color:"#64748b"}}>Username</label>
                    <div className="relative">
                      <span className="absolute inset-y-0 left-0 pl-3 flex items-center" style={{color:"#475569"}}>
                        <User className="w-4 h-4" />
                      </span>
                      <input
                        type="text"
                        className="w-full pl-10 pr-4 py-3 rounded-xl text-white placeholder-slate-600 outline-none text-sm transition-all"
                        style={{background:"rgba(255,255,255,0.05)", border:"1px solid rgba(255,255,255,0.08)"}}
                        placeholder="Enter username"
                        value={username}
                        onChange={e => setUsername(e.target.value)}
                        onFocus={e => e.currentTarget.style.border="1px solid rgba(74,162,255,0.4)"}
                        onBlur={e => e.currentTarget.style.border="1px solid rgba(255,255,255,0.08)"}
                        required
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-bold uppercase tracking-widest mb-2"
                      style={{color:"#64748b"}}>Password</label>
                    <div className="relative">
                      <span className="absolute inset-y-0 left-0 pl-3 flex items-center" style={{color:"#475569"}}>
                        <Lock className="w-4 h-4" />
                      </span>
                      <input
                        type="password"
                        className="w-full pl-10 pr-4 py-3 rounded-xl text-white placeholder-slate-600 outline-none text-sm transition-all"
                        style={{background:"rgba(255,255,255,0.05)", border:"1px solid rgba(255,255,255,0.08)"}}
                        placeholder="Enter password"
                        value={password}
                        onChange={e => setPassword(e.target.value)}
                        onFocus={e => e.currentTarget.style.border="1px solid rgba(74,162,255,0.4)"}
                        onBlur={e => e.currentTarget.style.border="1px solid rgba(255,255,255,0.08)"}
                        required
                      />
                    </div>
                  </div>

                  <button
                    type="submit"
                    disabled={loading}
                    className="w-full font-bold py-3.5 px-6 rounded-xl flex items-center justify-center gap-2 mt-2 text-sm tracking-widest uppercase disabled:opacity-50 transition-all"
                    style={{background:"#1a5fa8", color:"white"}}
                    onMouseEnter={e => !loading && (e.currentTarget.style.background="#2272c3")}
                    onMouseLeave={e => (e.currentTarget.style.background="#1a5fa8")}
                  >
                    {loading ? "Authenticating..." : (
                      <>Authenticate Staff <ArrowRight className="w-4 h-4" /></>
                    )}
                  </button>
                </form>

                <p className="text-center text-xs mt-6" style={{color:"#334155"}}>
                  Authorized personnel access only.<br />Audit tracking active.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* ── Secure Access badge — bottom left ── */}
        <div className="relative z-10 px-8 pb-6">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
              style={{background:"rgba(255,255,255,0.06)", border:"1px solid rgba(255,255,255,0.08)"}}>
              <ShieldAlert className="w-4 h-4" style={{color:"#4ca2ff"}} />
            </div>
            <div>
              <p className="text-white text-xs font-bold">Secure Access</p>
              <p className="text-xs" style={{color:"#334155"}}>This system is for authorized municipal<br />personnel only.</p>
            </div>
          </div>
        </div>

      </div>

      {/* ── Footer ── */}
      <div className="relative z-10 border-t px-8 py-4 grid grid-cols-1 sm:grid-cols-3 gap-4 items-center"
        style={{borderColor:"rgba(255,255,255,0.06)", background:"rgba(5,10,22,0.95)"}}>

        <div className="flex items-center gap-3">
          <div className="relative w-9 h-9 flex-shrink-0 rounded-full bg-white overflow-hidden ring-1 ring-white/20">
            <Image src="/dipaculao-logo.png" alt="" fill className="object-contain p-0.5" />
          </div>
          <div>
            <p className="text-white text-sm font-bold">Bayan ng Dipaculao</p>
            <p className="text-xs" style={{color:"#334155"}}>Province of Aurora</p>
          </div>
        </div>

        <div className="flex items-start gap-3">
          <Lock className="w-4 h-4 flex-shrink-0 mt-0.5" style={{color:"#334155"}} />
          <p className="text-xs leading-relaxed" style={{color:"#475569"}}>
            Data Privacy Act of 2012 (RA 10173)<br />
            and the Local Government Code (RA 7160).
          </p>
        </div>

        <div className="sm:text-right">
          <p className="text-xs leading-relaxed" style={{color:"#475569"}}>
            © 2026 Municipal Treasury Office of<br />
            Dipaculao, Aurora. All Rights Reserved.
          </p>
        </div>

      </div>
    </div>
  );
}
