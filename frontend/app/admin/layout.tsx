"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { 
  LayoutDashboard, 
  Building2, 
  CreditCard, 
  Database, 
  Users, 
  LogOut, 
  ShieldAlert,
  User as UserIcon,
  Menu,
  X,
  CheckCircle2,
  AlertTriangle,
  FileBarChart,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<{ username: string; role: string; id?: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    // Exclude login page from auth check
    if (pathname === "/admin/login") {
      setLoading(false);
      return;
    }

    // Fetch a CSRF token on mount so state-changing requests are protected.
    fetch("/api/v1/api/auth/csrf", { credentials: "include" }).catch(() => {});

    // The Edge middleware (middleware.ts) already guards all /admin/* routes
    // and redirects unauthenticated users to /admin/login before React renders.
    // We only need to fetch the user's display data here — not re-validate auth.
    const fetchUser = async () => {
      try {
        const res = await fetch("/api/v1/me");
        if (!res.ok) {
          // Token present but invalid/expired — middleware missed it (cookie presence
          // check only). Let the server redirect handle it.
          router.push("/admin/login");
          return;
        }
        const data = await res.json();
        setUser(data);
        // Store non-sensitive display data in sessionStorage (cleared on tab close).
        // Never store tokens here — they live in the httpOnly cookie only.
        sessionStorage.setItem("mto_user", JSON.stringify({ username: data.username, role: data.role }));
        setLoading(false);
      } catch {
        router.push("/admin/login");
      }
    };

    fetchUser();
  }, [pathname, router]);

  const handleLogout = async () => {
    try {
      // Send refresh token so the server can revoke it in the DB.
      // Without this, the refresh token stays valid for 7 days after logout.
      const storedUser = sessionStorage.getItem("mto_user");
      const refreshToken = storedUser ? JSON.parse(storedUser).refresh_token : null;
      await fetch("/api/v1/api/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken ?? "" }),
      });
    } catch {}
    // Clear sessionStorage — never localStorage (we no longer write there)
    sessionStorage.removeItem("mto_user");
    // router.push for SPA navigation — no full page reload
    router.push("/admin/login");
  };

  if (pathname === "/admin/login") {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="animate-pulse text-center">
          <div className="w-12 h-12 border-4 border-[#1f4e78] border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-slate-400 text-sm font-medium">Securing access connection...</p>
        </div>
      </div>
    );
  }

  const menuItems = [
    { name: "Dashboard", path: "/admin/dashboard", icon: LayoutDashboard },
    { name: "Property Registry", path: "/admin/properties", icon: Building2 },
    { name: "Cashier Ledger", path: "/admin/cashier", icon: CreditCard },
    { name: "Collections", path: "/admin/collections", icon: AlertTriangle },
    { name: "Compliant Properties", path: "/admin/compliant", icon: CheckCircle2 },
    { name: "Reports", path: "/admin/reports", icon: FileBarChart },
    { name: "DB & Maintenance", path: "/admin/system", icon: Database },
  ];

  // Admin-only views
  const isAdmin = user?.role === "admin";
  if (isAdmin) {
    menuItems.push({ name: "Staff Management", path: "/admin/users", icon: Users });
  }

  return (
    <div className="min-h-screen bg-slate-950 flex text-slate-100 font-sans">
      {/* Sidebar - Desktop */}
      <aside className="hidden lg:flex flex-col w-64 bg-slate-900 border-r border-slate-800 shrink-0">
        <div className="h-20 flex items-center gap-3 px-6 border-b border-slate-800">
          <div className="relative w-10 h-10 flex-shrink-0 rounded-full bg-white shadow ring-2 ring-white/20 overflow-hidden">
            <Image
              src="/dipaculao-logo.png"
              alt="Dipaculao Logo"
              fill
              className="object-contain p-0.5"
              priority
            />
          </div>
          <div>
            <h1 className="font-extrabold text-sm tracking-tight text-white uppercase">Municipal Treasury</h1>
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Admin Terminal</p>
          </div>
        </div>

        <nav className="flex-1 px-4 py-6 space-y-2">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.path;
            return (
              <Link
                key={item.path}
                href={item.path}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl font-bold text-sm transition-all ${
                  active 
                    ? "bg-[#1f4e78] text-white shadow-lg shadow-[#1f4e78]/25" 
                    : "text-slate-400 hover:bg-slate-800 hover:text-white"
                }`}
              >
                <Icon className="w-5 h-5" />
                {item.name}
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-slate-800 bg-slate-900/50">

          {/* Secure Access card */}
          <div className="flex items-center gap-3 p-3 rounded-xl mb-3"
            style={{background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.06)"}}>
            <div className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{background:"rgba(31,78,120,0.4)", border:"1px solid rgba(74,162,255,0.2)"}}>
              <ShieldAlert className="w-4 h-4" style={{color:"#4ca2ff"}} />
            </div>
            <div>
              <p className="text-white text-xs font-bold">Secure Access</p>
              <p className="text-[10px] text-slate-500 leading-relaxed">
                Authorized personnel only.<br />All activities are logged.
              </p>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 font-bold text-xs uppercase tracking-wider rounded-xl transition-colors border border-red-500/20"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Mobile Drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden bg-slate-950/80 backdrop-blur-sm">
          <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col animate-slide-in">
            <div className="h-20 flex items-center justify-between px-6 border-b border-slate-800">
              <div className="flex items-center gap-3">
                <div className="relative w-10 h-10 flex-shrink-0 rounded-full bg-white shadow ring-2 ring-white/20 overflow-hidden">
                  <Image
                    src="/dipaculao-logo.png"
                    alt="Dipaculao Logo"
                    fill
                    className="object-contain p-0.5"
                  />
                </div>
                <h1 className="font-extrabold text-sm text-white">Municipal Treasury</h1>
              </div>
              <button onClick={() => setMobileOpen(false)} className="text-slate-400 hover:text-white">
                <X className="w-6 h-6" />
              </button>
            </div>

            <nav className="flex-1 px-4 py-6 space-y-2">
              {menuItems.map((item) => {
                const Icon = item.icon;
                const active = pathname === item.path;
                return (
                  <Link
                    key={item.path}
                    href={item.path}
                    onClick={() => setMobileOpen(false)}
                    className={`flex items-center gap-3 px-4 py-3 rounded-xl font-bold text-sm transition-all ${
                      active 
                        ? "bg-[#1f4e78] text-white" 
                        : "text-slate-400 hover:bg-slate-800 hover:text-white"
                    }`}
                  >
                    <Icon className="w-5 h-5" />
                    {item.name}
                  </Link>
                );
              })}
            </nav>

            <div className="p-4 border-t border-slate-800">
              <button
                onClick={handleLogout}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-red-500/10 text-red-400 font-bold text-xs uppercase tracking-wider rounded-xl transition-colors border border-red-500/20"
              >
                <LogOut className="w-4 h-4" />
                Sign Out
              </button>
            </div>
          </aside>
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Header */}
        <header className="h-20 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-6 lg:px-8">
          <button
            onClick={() => setMobileOpen(true)}
            className="lg:hidden p-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-xl"
          >
            <Menu className="w-6 h-6" />
          </button>

          <div className="hidden lg:block">
            <h2 className="text-lg font-black text-white uppercase tracking-tight">
              {menuItems.find(item => pathname === item.path)?.name || "Staff Management"}
            </h2>
          </div>

          <div className="flex items-center gap-4">
            <Link 
              href="/" 
              target="_blank" 
              className="text-xs font-bold uppercase tracking-wider text-slate-400 hover:text-[#4ca2ff] transition-colors border border-slate-700/80 px-3 py-1.5 rounded-lg"
            >
              Public Search Site
            </Link>
            
            <div className="h-6 w-px bg-slate-800"></div>

            <div className="flex items-center gap-2 text-slate-300">
              <UserIcon className="w-4 h-4 text-slate-500" />
              <span className="text-sm font-bold">{user?.username}</span>
            </div>
          </div>
        </header>

        {/* Content body */}
        <main className="flex-1 overflow-y-auto p-6 lg:p-8 bg-slate-950">
          {children}
        </main>
      </div>
    </div>
  );
}
