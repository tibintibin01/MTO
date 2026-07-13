"use client";

import { usePathname } from "next/navigation";
import Image from "next/image";
import { ArrowRight, Clock3, Landmark, MapPin } from "lucide-react";

/**
 * Wraps the public header + footer.
 * Hidden on /admin/* routes — the admin area has its own full-screen layout.
 */
export function PublicShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isAdmin = pathname.startsWith("/admin");

  if (isAdmin) {
    // Admin routes render their own layout — skip public chrome entirely
    return <>{children}</>;
  }

  return (
    <div className="min-h-full flex flex-col">

      {/* ── Top bar ── */}
      <div className="bg-[#0f2a5e] text-white text-xs py-1.5 text-center tracking-widest font-medium">
        OFFICIAL WEBSITE — MUNICIPAL TREASURY OFFICE OF DIPACULAO, AURORA
      </div>

      {/* ── Main header ── */}
      <header className="bg-gradient-to-r from-[#1a3a6b] via-[#1f4e78] to-[#1a3a6b] text-white shadow-xl">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between gap-4">
          <a href="/" className="flex items-center gap-4 group">
            {/* White circle badge — standard government seal presentation */}
            <div className="relative w-14 h-14 flex-shrink-0 rounded-full bg-white shadow-lg ring-2 ring-white/30 overflow-hidden">
              <Image
                src="/dipaculao-logo.png"
                alt="Official Logo of Dipaculao, Aurora"
                fill
                className="object-contain p-0.5"
                priority
              />
            </div>
            <div>
              <p className="text-xs font-semibold tracking-widest text-blue-200 uppercase">
                Republic of the Philippines
              </p>
              <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight leading-tight">
                Bayan ng Dipaculao
              </h1>
              <p className="text-sm text-blue-200 font-medium tracking-wide">
                Municipal Treasury Office — Aurora
              </p>
            </div>
          </a>

          <nav className="hidden sm:flex items-center gap-6 text-sm font-semibold">
            <div className="flex items-center gap-1 px-5 py-2.5 rounded-2xl"
              style={{
                background:"rgba(255,255,255,0.1)",
                backdropFilter:"blur(12px)",
                WebkitBackdropFilter:"blur(12px)",
                border:"1px solid rgba(255,255,255,0.15)",
              }}>
              <a href="/" className="flex items-center gap-2 text-white/80 hover:text-white transition-colors px-3 py-1">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
                </svg>
                Property Search
              </a>
              <div className="w-px h-4 bg-white/20 mx-1" />
              <a href="/help" className="flex items-center gap-2 text-white/80 hover:text-white transition-colors px-3 py-1">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>
                </svg>
                Help &amp; Support
              </a>
            </div>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        {children}
      </main>

      {/* ── Footer ── */}
      <footer className="relative mt-auto overflow-hidden bg-gradient-to-b from-[#173d70] to-[#0b2450] text-white">
        <div className="absolute inset-0 opacity-[0.035]" style={{backgroundImage:"radial-gradient(circle,#fff 1px,transparent 1px)",backgroundSize:"24px 24px"}} />

        <div className="relative border-b border-white/10">
          <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-8 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.22em] text-yellow-300">Municipal assistance</p>
              <h2 className="mt-1 text-xl font-black">Need help with a payment or property record?</h2>
              <p className="mt-1 text-sm text-blue-200">Visit the Municipal Treasury Office during official business hours.</p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="flex items-center gap-3 rounded-2xl border border-white/15 bg-white/10 px-4 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] backdrop-blur">
                <Clock3 className="h-5 w-5 text-yellow-300" />
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-wider text-blue-300">Office hours</p>
                  <p className="text-sm font-bold">Mon-Fri, 8:00 AM-5:00 PM</p>
                </div>
              </div>
              <a href="/help" className="group flex items-center justify-between gap-5 rounded-2xl bg-yellow-400 px-5 py-3 text-sm font-black text-slate-950 shadow-[0_12px_28px_rgba(250,204,21,0.22)] transition-all hover:-translate-y-0.5 hover:bg-yellow-300">
                Help &amp; Support
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </a>
            </div>
          </div>
        </div>

        <div className="relative max-w-6xl mx-auto px-4 py-10 grid grid-cols-1 sm:grid-cols-3 gap-10">
          <div className="flex flex-col items-start gap-3">
            <div className="flex items-center gap-3">
              <div className="relative w-12 h-12 flex-shrink-0 rounded-full bg-white shadow ring-2 ring-white/20 overflow-hidden">
                <Image
                  src="/dipaculao-logo.png"
                  alt="Logo of Dipaculao"
                  fill
                  className="object-contain p-0.5"
                />
              </div>
              <div>
                <p className="font-bold text-sm">Bayan ng Dipaculao</p>
                <p className="text-xs text-blue-300">Province of Aurora</p>
              </div>
            </div>
            <div className="flex items-start gap-2 text-xs leading-relaxed text-blue-300">
              <MapPin className="mt-0.5 h-4 w-4 flex-shrink-0 text-yellow-300" />
              <p>Municipal Treasury Office<br />Dipaculao, Aurora, Philippines</p>
            </div>
          </div>

          <div>
            <p className="text-xs font-bold tracking-widest text-blue-300 uppercase mb-3">Quick Links</p>
            <ul className="space-y-3 text-sm text-blue-100">
              <li><a href="/" className="group flex items-center gap-2 hover:text-yellow-300 transition-colors"><Landmark className="h-4 w-4" /> Property Search</a></li>
              <li><a href="/help" className="group flex items-center gap-2 hover:text-yellow-300 transition-colors"><ArrowRight className="h-4 w-4" /> Help &amp; Support</a></li>
            </ul>
          </div>

          <div>
            <p className="text-xs font-bold tracking-widest text-blue-300 uppercase mb-3">Legal</p>
            <p className="text-xs text-blue-300 leading-relaxed">
              Data collected is governed by the{" "}
              <strong className="text-white">Data Privacy Act of 2012 (RA 10173)</strong> and the{" "}
              <strong className="text-white">Local Government Code (RA 7160)</strong>.
            </p>
            <p className="text-xs text-blue-400 mt-3">Data available from 2023 onwards.</p>
          </div>
        </div>

        <div className="relative border-t border-white/10 py-4 text-center">
          <p className="text-xs text-blue-400">
            &copy; {new Date().getFullYear()} Municipal Treasury Office of Dipaculao, Aurora. All Rights Reserved.
          </p>
        </div>
      </footer>

    </div>
  );
}
