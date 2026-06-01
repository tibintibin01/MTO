"use client";

import { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  Search,
  Download,
  RefreshCw,
  FileText,
  Bell,
  Clock,
  Banknote,
} from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

interface WorklistItem {
  id: number;
  td_number: string;
  owner_name: string;
  location: string;
  barangay: string;
  total_due: number;
  total_paid: number;
  balance: number;
  earliest_year: number | null;
  years_billed: number;
  age_days: number;
  aging_bucket: string;
}

interface Summary {
  delinquent_count: number;
  total_balance: number;
  aging_totals: Record<string, number>;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  "₱ " + (n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const AGING_FILTERS = [
  { label: "All", days: 0 },
  { label: "30+ days", days: 30 },
  { label: "60+ days", days: 60 },
  { label: "90+ days", days: 90 },
  { label: "120+ days", days: 120 },
];

function AgingBadge({ bucket }: { bucket: string }) {
  const map: Record<string, string> = {
    CURRENT: "text-slate-400 bg-slate-500/10 border-slate-500/20",
    "30": "text-yellow-400 bg-yellow-500/10 border-yellow-500/20",
    "60": "text-orange-400 bg-orange-500/10 border-orange-500/20",
    "90": "text-red-400 bg-red-500/10 border-red-500/20",
    "120+": "text-red-300 bg-red-600/20 border-red-500/40",
  };
  const label = bucket === "CURRENT" ? "< 30d" : `${bucket}d`;
  return (
    <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full uppercase border ${map[bucket] || map.CURRENT}`}>
      {label}
    </span>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────

export default function CollectionsPage() {
  const searchParams = useSearchParams();
  const [items, setItems] = useState<WorklistItem[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [barangays, setBarangays] = useState<string[]>([]);
  const [selectedBarangay, setSelectedBarangay] = useState(
    () => searchParams.get("barangay") || "ALL"
  );
  const [minAge, setMinAge] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  // Load barangay list once for the filter dropdown
  useEffect(() => {
    fetch("/api/v1/properties/barangays", { credentials: "include", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => (r.ok ? r.json() : []))
      .then((data) => setBarangays(Array.isArray(data) ? data : []))
      .catch(() => {});
  }, []);

  const fetchWorklist = useCallback(
    async (reset = true) => {
      setLoading(true);
      setError("");
      try {
        const params = new URLSearchParams({ limit: "50", min_age_days: String(minAge) });
        if (selectedBarangay !== "ALL") params.set("barangay", selectedBarangay);
        params.set("offset", reset ? "0" : String(offset));

        const res = await fetch(`/api/v1/billing/collections?${params}`, {
          credentials: "include",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (res.status === 401) { window.location.href = "/admin/login"; return; }
        if (!res.ok) throw new Error("Failed to load collections worklist.");
        const data = await res.json();

        setSummary(data.summary ?? null);
        setHasMore(data.has_more ?? false);
        setOffset(data.next_offset ?? 0);
        setItems(reset ? (data.items ?? []) : (prev) => [...prev, ...(data.items ?? [])]);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Error loading worklist.");
      } finally {
        setLoading(false);
      }
    },
    [selectedBarangay, minAge, offset]
  );

  // Refetch when filters change
  useEffect(() => {
    setOffset(0);
    fetchWorklist(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBarangay, minAge]);

  // Client-side text filter (name / TDN) over the loaded page set
  const filtered = search.trim()
    ? items.filter(
        (p) =>
          p.owner_name.toLowerCase().includes(search.toLowerCase()) ||
          p.td_number.toLowerCase().includes(search.toLowerCase())
      )
    : items;

  // Open a generated PDF (notice or SOA) in a new tab
  const openPdf = async (propertyId: number, kind: "notice" | "statement") => {
    setBusyId(propertyId);
    try {
      const res = await fetch(`/api/v1/properties/${propertyId}/${kind}-pdf`, {
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!res.ok) throw new Error("PDF generation failed.");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      window.open(url, "_blank");
    } catch {
      setError("Could not generate the document. Please try again.");
    } finally {
      setBusyId(null);
    }
  };

  const exportCSV = () => {
    const header = ["TD Number", "Owner", "Barangay", "Balance", "Earliest Year", "Age (days)", "Bucket"].join(",");
    const rows = filtered.map((p) =>
      [p.td_number, `"${p.owner_name}"`, p.barangay, p.balance.toFixed(2), p.earliest_year ?? "", p.age_days, p.aging_bucket].join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `collections_${selectedBarangay}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Revenue Recovery</p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Collections Worklist</h1>
          <p className="text-slate-400 text-sm mt-1">Delinquent accounts prioritised by balance, aged from the earliest unpaid year.</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => { setOffset(0); fetchWorklist(true); }}
            className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs uppercase tracking-wider rounded-xl border border-slate-700 transition-all"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button
            onClick={exportCSV}
            disabled={filtered.length === 0}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#1f4e78] hover:bg-[#2c6ea1] disabled:opacity-40 text-white font-bold text-xs uppercase tracking-wider rounded-xl transition-all"
          >
            <Download className="w-4 h-4" /> Export CSV
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 text-sm text-red-300 font-bold">
          {error}
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-orange-500/10 text-orange-400 rounded-xl flex items-center justify-center">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">Delinquent</span>
          </div>
          <p className="text-3xl font-black text-white">{(summary?.delinquent_count ?? 0).toLocaleString()}</p>
          <p className="text-xs text-slate-500 mt-1">accounts with a balance</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-red-500/10 text-red-400 rounded-xl flex items-center justify-center">
              <Banknote className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">Total Receivable</span>
          </div>
          <p className="text-2xl font-black text-white">{fmt(summary?.total_balance ?? 0)}</p>
          <p className="text-xs text-slate-500 mt-1">outstanding balance</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-red-600/20 text-red-300 rounded-xl flex items-center justify-center">
              <Clock className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">90+ Days</span>
          </div>
          <p className="text-2xl font-black text-white">
            {fmt((summary?.aging_totals?.["90"] ?? 0) + (summary?.aging_totals?.["120+"] ?? 0))}
          </p>
          <p className="text-xs text-slate-500 mt-1">aged, high-priority</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-yellow-500/10 text-yellow-400 rounded-xl flex items-center justify-center">
              <Clock className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">30–60 Days</span>
          </div>
          <p className="text-2xl font-black text-white">
            {fmt((summary?.aging_totals?.["30"] ?? 0) + (summary?.aging_totals?.["60"] ?? 0))}
          </p>
          <p className="text-xs text-slate-500 mt-1">recently overdue</p>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col lg:flex-row gap-3 lg:items-center">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Filter loaded rows by name or TDN..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-4 py-2.5 bg-slate-950 border border-slate-800 rounded-xl text-white text-sm placeholder-slate-500 outline-none focus:ring-2 focus:ring-[#1f4e78]/50"
          />
        </div>

        <select
          value={selectedBarangay}
          onChange={(e) => setSelectedBarangay(e.target.value)}
          className="bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]/50"
        >
          <option value="ALL">All Barangays</option>
          {barangays.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>

        <div className="flex gap-1 bg-slate-950 border border-slate-800 rounded-xl p-1">
          {AGING_FILTERS.map((f) => (
            <button
              key={f.days}
              onClick={() => setMinAge(f.days)}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-colors ${
                minAge === f.days ? "bg-[#1f4e78] text-white" : "text-slate-400 hover:text-white"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Worklist table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="overflow-auto" style={{ maxHeight: "calc(100vh - 460px)" }}>
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10">
              <tr className="bg-slate-950/95 border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider font-extrabold backdrop-blur">
                <th className="px-6 py-3 text-left">Priority</th>
                <th className="px-6 py-3 text-left">TD Number</th>
                <th className="px-6 py-3 text-left">Owner</th>
                <th className="px-6 py-3 text-left">Barangay</th>
                <th className="px-6 py-3 text-right">Balance</th>
                <th className="px-6 py-3 text-center">Since</th>
                <th className="px-6 py-3 text-center">Aging</th>
                <th className="px-6 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loading && items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center text-slate-500 font-bold">
                    <div className="w-8 h-8 border-2 border-[#1f4e78] border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                    Loading worklist...
                  </td>
                </tr>
              ) : filtered.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center text-slate-500 font-bold">
                    No delinquent accounts match the current filters. 🎉
                  </td>
                </tr>
              ) : (
                filtered.map((p, idx) => (
                  <tr key={p.id} className="hover:bg-slate-800/30 transition-colors">
                    <td className="px-6 py-3 text-slate-500 font-mono text-xs">#{idx + 1}</td>
                    <td className="px-6 py-3 font-black text-white">{p.td_number}</td>
                    <td className="px-6 py-3 font-semibold text-slate-200">{p.owner_name}</td>
                    <td className="px-6 py-3 text-slate-400">{p.barangay}</td>
                    <td className="px-6 py-3 text-right font-black text-red-400">{fmt(p.balance)}</td>
                    <td className="px-6 py-3 text-center text-slate-400">{p.earliest_year ?? "—"}</td>
                    <td className="px-6 py-3 text-center">
                      <AgingBadge bucket={p.aging_bucket} />
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex items-center justify-center gap-2">
                        <button
                          onClick={() => openPdf(p.id, "notice")}
                          disabled={busyId === p.id}
                          title="Generate delinquency notice"
                          className="flex items-center gap-1 px-2.5 py-1.5 bg-orange-500/10 hover:bg-orange-500/20 text-orange-400 rounded-lg border border-orange-500/20 text-xs font-bold transition-colors disabled:opacity-50"
                        >
                          <Bell className="w-3.5 h-3.5" /> Notice
                        </button>
                        <button
                          onClick={() => openPdf(p.id, "statement")}
                          disabled={busyId === p.id}
                          title="Generate statement of account"
                          className="flex items-center gap-1 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg border border-slate-700 text-xs font-bold transition-colors disabled:opacity-50"
                        >
                          <FileText className="w-3.5 h-3.5" /> SOA
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {hasMore && !search && (
          <div className="px-6 py-4 border-t border-slate-800 text-center">
            <button
              onClick={() => fetchWorklist(false)}
              disabled={loading}
              className="px-6 py-2.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 font-bold text-xs uppercase tracking-wider rounded-xl border border-slate-700 transition-all"
            >
              {loading ? "Loading..." : "Load More"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
