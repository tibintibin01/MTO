"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { 
  DollarSign, 
  Building2, 
  TrendingUp, 
  TrendingDown, 
  Activity,
  ArrowRight,
  RefreshCw,
  Percent,
  AlertTriangle
} from "lucide-react";
import { RevenueTrendChart } from "../../components/RevenueTrendChart";

export default function AdminDashboard() {
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  const fetchDashboard = async () => {
    try {
      setError("");
      // The access_token is stored as an httpOnly cookie set by /api/auth/login.
      // Browsers send it automatically — do NOT read it from localStorage
      // (httpOnly cookies are intentionally inaccessible to JavaScript).
      const res = await fetch("/api/v1/api/analytics/dashboard", {
        credentials: "include",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      });

      if (res.status === 401) {
        // Session expired or not logged in — redirect to login
        window.location.href = "/admin/login";
        return;
      }

      if (!res.ok) {
        throw new Error("Failed to load treasury analytics data.");
      }

      const json = await res.json();
      setData(json);
      setBackendOnline(true);
    } catch (err: any) {
      setError(err.message);
      setData(null);
      setBackendOnline(false);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchDashboard();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchDashboard();
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 animate-pulse">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-32 bg-slate-900 border border-slate-800 rounded-2xl"></div>
        ))}
        <div className="col-span-full h-96 bg-slate-900 border border-slate-800 rounded-2xl"></div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center gap-4">
        <div className="w-14 h-14 bg-red-500/10 rounded-2xl flex items-center justify-center border border-red-500/20">
          <Activity className="w-7 h-7 text-red-400" />
        </div>
        <div>
          <p className="text-lg font-black text-white">Backend Unreachable</p>
          <p className="text-slate-400 text-sm mt-1 max-w-sm">
            The API server is not responding. Start the backend with{" "}
            <code className="text-slate-300 bg-slate-800 px-1.5 py-0.5 rounded text-xs">run_system.bat</code>{" "}
            then refresh this page.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#1f4e78] hover:bg-[#2c6ea1] text-white font-bold text-sm rounded-xl transition-colors"
        >
          <RefreshCw className="w-4 h-4" /> Retry
        </button>
      </div>
    );
  }

  const summary = data?.summary || {
    total_receivables: 0,
    total_collected: 0,
    collection_rate: 0,
    total_properties: 0,
    active_delinquencies: 0
  };

  const lastYear = data?.last_year || {
    total_collected: 0,
    total_receivables: 0,
    collection_rate: 0,
    total_properties: 0,
  };

  // Compute % change vs last year
  const pctChange = (current: number, previous: number): number | null => {
    if (!previous || previous === 0) return null;
    return ((current - previous) / previous) * 100;
  };

  const YoyBadge = ({ current, previous }: { current: number; previous: number }) => {
    const pct = pctChange(current, previous);
    if (pct === null) return <span className="text-[10px] text-slate-600">No prior year data</span>;
    const positive = pct >= 0;
    return (
      <div className={`flex items-center gap-1 text-[10px] font-bold mt-1 ${positive ? "text-emerald-400" : "text-red-400"}`}>
        <span>{positive ? "↑" : "↓"}</span>
        <span>{Math.abs(pct).toFixed(1)}% vs last year</span>
      </div>
    );
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Top Header Actions */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Real-time Telemetry</p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Municipal Ledger</h1>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-4 py-2 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded-xl font-bold text-xs uppercase tracking-wider text-slate-300 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          {refreshing ? "Refreshing..." : "Refresh Stats"}
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-slate-900 border border-slate-800/80 rounded-2xl p-6 relative overflow-hidden group hover:border-[#1f4e78]/60 transition-all shadow-lg shadow-black/10">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-blue-500/10 text-blue-400 rounded-xl flex items-center justify-center border border-blue-500/20">
              <DollarSign className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-extrabold text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded-full">
              ALL YEARS
            </span>
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Total Collection Receivables</p>
          <h3 className="text-2xl font-black text-white mt-1">₱ {(summary.total_receivables || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</h3>
          <YoyBadge current={summary.total_receivables || 0} previous={lastYear.total_receivables || 0} />
        </div>

        <div className="bg-slate-900 border border-slate-800/80 rounded-2xl p-6 relative overflow-hidden group hover:border-[#1f4e78]/60 transition-all shadow-lg shadow-black/10">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-green-500/10 text-green-400 rounded-xl flex items-center justify-center border border-green-500/20">
              <DollarSign className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-extrabold text-green-400 bg-green-500/10 border border-green-500/20 px-2 py-0.5 rounded-full">
              POSTED
            </span>
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Actual Collected Revenue</p>
          <h3 className="text-2xl font-black text-green-400 mt-1">₱ {(summary.total_collected || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</h3>
          <YoyBadge current={summary.total_collected || 0} previous={lastYear.total_collected || 0} />
        </div>

        <div className="bg-slate-900 border border-slate-800/80 rounded-2xl p-6 relative overflow-hidden group hover:border-[#1f4e78]/60 transition-all shadow-lg shadow-black/10">
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-indigo-500/10 text-indigo-400 rounded-xl flex items-center justify-center border border-indigo-500/20">
              <Percent className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-extrabold text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded-full">
              TARGET 80%
            </span>
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Treasury Collection Efficiency</p>
          <h3 className="text-2xl font-black text-white mt-1">
            {(summary.total_receivables > 0
              ? ((summary.total_collected / summary.total_receivables) * 100)
              : 0
            ).toFixed(2)} %
          </h3>
          <YoyBadge current={summary.collection_rate || 0} previous={lastYear.collection_rate || 0} />
        </div>

        <button
          type="button"
          onClick={() => router.push("/admin/collections")}
          className="text-left bg-slate-900 border border-slate-800/80 rounded-2xl p-6 relative overflow-hidden group hover:border-orange-500/60 transition-all shadow-lg shadow-black/10 cursor-pointer focus:outline-none focus:ring-2 focus:ring-orange-500/50"
          title="View the collections worklist"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-10 bg-orange-500/10 text-orange-400 rounded-xl flex items-center justify-center border border-orange-500/20">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-extrabold text-orange-400 bg-orange-500/10 border border-orange-500/20 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Activity className="w-3 h-3" /> ACTION
            </span>
          </div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Active Delinquencies</p>
          <h3 className="text-2xl font-black text-white mt-1">{(summary.active_delinquencies || 0).toLocaleString()} Accounts</h3>
          <div className="flex items-center gap-1 text-[10px] font-bold mt-1 text-orange-400">
            <span>{(summary.total_properties || 0).toLocaleString()} total properties</span>
            <ArrowRight className="w-3 h-3" />
          </div>
        </button>
      </div>

      {/* Barangay distribution and trend charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Barangay Breakdown Table */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 lg:col-span-2 shadow-xl shadow-black/15 flex flex-col" style={{height:"420px"}}>
          <h3 className="text-base font-bold text-white uppercase tracking-wider mb-4 flex items-center gap-2 flex-shrink-0">
            <Building2 className="w-5 h-5 text-[#4ca2ff]" />
            Barangay Treasury Contribution
          </h3>

          <div className="overflow-auto flex-1 min-h-0">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-slate-900 z-10">
                <tr className="border-b border-slate-800 text-slate-400 font-extrabold text-xs uppercase tracking-wider">
                  <th className="pb-3 font-extrabold">Barangay Name</th>
                  <th className="pb-3 text-right font-extrabold">Receivables</th>
                  <th className="pb-3 text-right font-extrabold">Collected</th>
                  <th className="pb-3 text-right font-extrabold">Efficiency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {(data?.barangays || []).map((b: any, i: number) => (
                  <tr
                    key={i}
                    onClick={() => router.push(`/admin/collections?barangay=${encodeURIComponent(b.name)}`)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        router.push(`/admin/collections?barangay=${encodeURIComponent(b.name)}`);
                      }
                    }}
                    tabIndex={0}
                    role="button"
                    title={`View delinquents in ${b.name}`}
                    className="hover:bg-slate-850/50 transition-colors cursor-pointer focus:outline-none focus:bg-slate-800/60"
                  >
                    <td className="py-3 font-bold text-white">{b.name}</td>
                    <td className="py-3 text-right text-slate-400">P {(b.value || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td className="py-3 text-right font-bold text-green-400">P {(b.collected || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td className="py-3 text-right">
                      <div className="flex items-center justify-end gap-3">
                        <span className="font-bold text-xs">{(b.percentage || 0).toFixed(1)}%</span>
                        <div className="w-16 h-2 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-blue-500 to-[#1f4e78] rounded-full"
                            style={{ width: `${b.percentage || 0}%` }}
                          />
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Monthly Trend Display */}
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl shadow-black/15 flex flex-col" style={{height:"420px"}}>
          <h3 className="text-base font-bold text-white uppercase tracking-wider mb-6 flex items-center gap-2">
            <TrendingUp className="w-5 h-5 text-[#4ca2ff]" />
            Monthly Revenue Trend
          </h3>

          <div className="flex-1 min-h-0">
            <RevenueTrendChart data={data?.trend || []} />
          </div>

          <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/80 flex-shrink-0 mt-3">
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Active System Status</p>
              <div className="flex items-center gap-2 mt-1">
                {error ? (
                  <>
                    <div className="w-2.5 h-2.5 rounded-full bg-red-500"></div>
                    <span className="text-xs font-bold text-red-400">Backend unreachable — data may be stale</span>
                  </>
                ) : (
                  <>
                    <div className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse"></div>
                    <span className="text-xs font-bold text-white">Live — synced with database</span>
                  </>
                )}
              </div>
            </div>
          </div>
      </div>
    </div>
  );
}
