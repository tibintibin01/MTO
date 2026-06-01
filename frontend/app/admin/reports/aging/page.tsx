"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, Download, RefreshCw, AlertCircle, Clock } from "lucide-react";

interface AgingSummary {
  delinquent_count: number;
  total_balance: number;
  aging_totals: Record<string, number>;
}

const peso = (n: number) =>
  "₱ " + (n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// CSV formula-injection guard (mirrors backend utils.sanitizer.csv_safe_cell)
const csvSafe = (v: unknown): string => {
  const s = v == null ? "" : String(v);
  return s && "=+-@\t\r".includes(s[0]) ? "'" + s : s;
};

const BUCKETS: { key: string; label: string; color: string }[] = [
  { key: "CURRENT", label: "Current (< 30d)", color: "text-slate-300" },
  { key: "30", label: "30 days", color: "text-yellow-400" },
  { key: "60", label: "60 days", color: "text-orange-400" },
  { key: "90", label: "90 days", color: "text-red-400" },
  { key: "120+", label: "120+ days", color: "text-red-300" },
];

export default function AgingReport() {
  const [barangays, setBarangays] = useState<string[]>([]);
  const [selectedBarangay, setSelectedBarangay] = useState("ALL");
  const [summary, setSummary] = useState<AgingSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/v1/properties/barangays", { credentials: "include", headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((r) => (r.ok ? r.json() : []))
      .then((d) => setBarangays(Array.isArray(d) ? d : []))
      .catch(() => {});
  }, []);

  const fetchAging = useCallback(async () => {
    setLoading(true);
    setError("");
    setSummary(null);
    try {
      const params = new URLSearchParams({ limit: "1" }); // we only need the summary
      if (selectedBarangay !== "ALL") params.set("barangay", selectedBarangay);
      const res = await fetch(`/api/v1/billing/collections?${params}`, {
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (res.status === 401) { window.location.href = "/admin/login"; return; }
      if (!res.ok) throw new Error("Failed to load aging report.");
      const data = await res.json();
      setSummary(data.summary ?? null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error loading aging report.");
    } finally {
      setLoading(false);
    }
  }, [selectedBarangay]);

  useEffect(() => { fetchAging(); }, [fetchAging]);

  const total = summary?.total_balance ?? 0;
  const pct = (amount: number) => (total > 0 ? (amount / total) * 100 : 0);

  const exportCSV = () => {
    if (!summary) return;
    const header = ["Aging Bucket", "Amount", "Percent of Total"].join(",");
    const rows = BUCKETS.map((b) => {
      const amt = summary.aging_totals[b.key] ?? 0;
      return [csvSafe(b.label), amt.toFixed(2), pct(amt).toFixed(1) + "%"].join(",");
    });
    const meta = [
      `Aging Report`,
      `Barangay: ${csvSafe(selectedBarangay)}`,
      `Generated: ${new Date().toISOString().slice(0, 10)}`,
      `Total Receivable: ${total.toFixed(2)}`,
      "",
    ];
    const csv = [...meta, header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aging_report_${selectedBarangay}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <Link href="/admin/reports" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white mb-2">
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Reports
          </Link>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Collections Risk</p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Aging Report</h1>
        </div>
        <div className="flex gap-3">
          <select
            value={selectedBarangay}
            onChange={(e) => setSelectedBarangay(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]/50"
          >
            <option value="ALL">All Barangays</option>
            {barangays.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <button
            onClick={fetchAging}
            className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs uppercase tracking-wider rounded-xl border border-slate-700 transition-all"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button
            onClick={exportCSV}
            disabled={!summary}
            className="flex items-center gap-2 px-4 py-2.5 bg-[#1f4e78] hover:bg-[#2c6ea1] disabled:opacity-40 text-white font-bold text-xs uppercase tracking-wider rounded-xl transition-all"
          >
            <Download className="w-4 h-4" /> Export CSV
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 flex gap-3 text-sm text-red-300">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span className="font-bold flex-1">{error}</span>
        </div>
      )}

      {loading ? (
        <div className="h-72 bg-slate-900 border border-slate-800 rounded-2xl animate-pulse" />
      ) : summary ? (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl shadow-black/15">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center gap-2">
            <Clock className="w-5 h-5 text-[#4ca2ff]" />
            <h2 className="font-black text-sm text-white uppercase tracking-wider">
              Aging Breakdown — {selectedBarangay === "ALL" ? "All Barangays" : selectedBarangay}
            </h2>
            <span className="ml-auto text-xs font-bold text-orange-400 bg-orange-500/10 border border-orange-500/20 px-2 py-0.5 rounded-full">
              {summary.delinquent_count.toLocaleString()} delinquent
            </span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-950/60 border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider font-extrabold">
                <th className="px-6 py-3 text-left">Aging Bucket</th>
                <th className="px-6 py-3 text-right">Amount</th>
                <th className="px-6 py-3 text-right">% of Total</th>
                <th className="px-6 py-3 text-left w-1/3">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {BUCKETS.map((b) => {
                const amt = summary.aging_totals[b.key] ?? 0;
                const p = pct(amt);
                return (
                  <tr key={b.key} className="hover:bg-slate-800/30 transition-colors">
                    <td className={`px-6 py-3 font-bold ${b.color}`}>{b.label}</td>
                    <td className="px-6 py-3 text-right font-black text-white">{peso(amt)}</td>
                    <td className="px-6 py-3 text-right text-slate-400">{p.toFixed(1)}%</td>
                    <td className="px-6 py-3">
                      <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-orange-500 to-red-500 rounded-full" style={{ width: `${p}%` }} />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="bg-slate-950/60 border-t-2 border-slate-700">
                <td className="px-6 py-3 font-black text-white uppercase tracking-wider">Total Receivable</td>
                <td className="px-6 py-3 text-right font-black text-emerald-400">{peso(total)}</td>
                <td className="px-6 py-3 text-right text-slate-400">100%</td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      ) : (
        !error && (
          <div className="py-16 text-center text-slate-500 font-bold bg-slate-900 border border-slate-800 rounded-2xl">
            No delinquent accounts found.
          </div>
        )
      )}
    </div>
  );
}
