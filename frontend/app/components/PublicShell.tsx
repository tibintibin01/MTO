"use client";

import { usePathname } from "next/navigation";
import Image from "next/image";

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
            <div className="relative w-20 h-20 flex-shrink-0">
              <Image
                src="/dipaculao-logo.png"
                alt="Official Logo of Dipaculao, Aurora"
                fill
                className="object-contain drop-shadow-lg"
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
            <a href="/" className="hover:text-yellow-300 transition-colors">
              Property Search
            </a>
            <a href="/help" className="hover:text-yellow-300 transition-colors">
              Help &amp; Support
            </a>
            <a
              href="/admin/login"
              className="bg-yellow-400 text-[#0f2a5e] px-4 py-2 rounded-lg font-bold hover:bg-yellow-300 transition-colors text-xs tracking-wide"
            >
              STAFF LOGIN
            </a>
          </nav>
        </div>
      </header>

      <main className="flex-1">
        {children}
      </main>

      {/* ── Footer ── */}
      <footer className="bg-[#0f2a5e] text-white mt-auto">
        <div className="max-w-7xl mx-auto px-4 py-10 grid grid-cols-1 sm:grid-cols-3 gap-8">
          <div className="flex flex-col items-start gap-3">
            <div className="flex items-center gap-3">
              <div className="relative w-12 h-12 flex-shrink-0">
                <Image
                  src="/dipaculao-logo.png"
                  alt="Logo of Dipaculao"
                  fill
                  className="object-contain opacity-90"
                />
              </div>
              <div>
                <p className="font-bold text-sm">Bayan ng Dipaculao</p>
                <p className="text-xs text-blue-300">Province of Aurora</p>
              </div>
            </div>
            <p className="text-xs text-blue-300 leading-relaxed">
              Municipal Treasury Office<br />
              Dipaculao, Aurora, Philippines
            </p>
          </div>

          <div>
            <p className="text-xs font-bold tracking-widest text-blue-300 uppercase mb-3">Quick Links</p>
            <ul className="space-y-2 text-sm text-blue-100">
              <li><a href="/" className="hover:text-yellow-300 transition-colors">Property Search</a></li>
              <li><a href="/help" className="hover:text-yellow-300 transition-colors">Help &amp; Support</a></li>
              <li><a href="/admin/login" className="hover:text-yellow-300 transition-colors">Staff Portal</a></li>
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

        <div className="border-t border-blue-900 py-4 text-center">
          <p className="text-xs text-blue-400">
            &copy; {new Date().getFullYear()} Municipal Treasury Office of Dipaculao, Aurora. All Rights Reserved.
          </p>
        </div>
      </footer>

    </div>
  );
}
