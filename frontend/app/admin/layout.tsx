"use client";

import { useEffect, useState } from "react";
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
  X
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [user, setUser] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    // Exclude login page from auth check
    if (pathname === "/admin/login") {
      setLoading(false);
      return;
    }

    const verifyAuth = async () => {
      try {
        const res = await fetch("/api/v1/me");
        if (!res.ok) {
          window.location.href = "/admin/login";
          return;
        }
        const data = await res.json();
        setUser(data);
        localStorage.setItem("mto_user", JSON.stringify(data));
        setLoading(false);
      } catch {
        window.location.href = "/admin/login";
      }
    };

    verifyAuth();
  }, [pathname]);

  const handleLogout = async () => {
    try {
      await fetch("/api/v1/api/auth/logout", { method: "POST" });
    } catch {}
    localStorage.removeItem("mto_token");
    localStorage.removeItem("mto_user");
    window.location.href = "/admin/login";
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
          <div className="w-10 h-10 bg-[#1f4e78]/20 border border-[#2c6ea1]/40 text-[#4ca2ff] rounded-xl flex items-center justify-center">
            <ShieldAlert className="w-5 h-5" />
          </div>
          <div>
            <h1 className="font-extrabold text-sm tracking-tight text-white uppercase">MTO Treasury</h1>
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
          <div className="flex items-center gap-3 px-2 py-3 rounded-xl mb-2">
            <div className="w-8 h-8 bg-slate-800 rounded-full flex items-center justify-center text-slate-300 font-black text-sm uppercase">
              {user?.username?.substring(0, 2)}
            </div>
            <div className="overflow-hidden">
              <p className="font-bold text-sm text-white truncate">{user?.username}</p>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-extrabold">{user?.role}</p>
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
                <div className="w-10 h-10 bg-[#1f4e78]/20 border border-[#2c6ea1]/40 text-[#4ca2ff] rounded-xl flex items-center justify-center">
                  <ShieldAlert className="w-5 h-5" />
                </div>
                <h1 className="font-extrabold text-sm text-white">MTO Panel</h1>
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
