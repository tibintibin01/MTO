"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, FileSpreadsheet, RefreshCw, AlertCircle, Landmark } from "lucide-react";

interface Receivables {
  report_year: number;
  beginning_receivable: number;
  current_year_assessment: number;
  collections: number;
  adjustments: number;
  ending_receivable: number;
}

const peso = (n: number) =>
  "₱ " + (n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: CURRENT_YEAR - 2022 }, (_, i) => CURRENT_YEAR - i);

export default function ReceivablesReport() {
  const [year, setYear] = useState(String(CURRENT_YEAR));
  const [data, setData] = useState<Receivables | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError("");
    setData(null); // never show stale/fabricated figures on error
    try {
      const res = await fetch(`/api/v1/billing/receivables-summary?year=${encodeURIComponent(year)}`, {
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (res.status === 401) { window.location.href = "/admin/login"; return; }
      if (!res.ok) throw new Error("Failed to load receivables statement.");
      setData(await res.json());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error loading receivables.");
    } finally {
      setLoading(false);
    }
  }, [year]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const exportExcel = async () => {
    setExporting(true);
    setError("");
    try {
      const res = await fetch("/api/v1/billing/export/excel", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ report_type: "receivables", year }),
      });
      if (!res.ok) throw new Error("Export failed.");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `MTO_RPT_Receivables_${year}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch {
      setError("Could not export the statement. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  const Row = ({ label, value, bold, sign }: { label: string; value: number; bold?: boolean; sign?: string }) => (
    <div className={`flex items-center justify-between px-6 py-4 ${bold ? "bg-slate-950/60" : ""}`}>
      <span className={`text-sm ${bold ? "font-black text-white uppercase tracking-wider" : "text-slate-300"}`}>
        {sign && <span className="text-slate-500 mr-2">{sign}</span>}{label}
      </span>
      <span className={`font-mono ${bold ? "text-lg font-black text-emerald-400" : "text-slate-200 font-bold"}`}>
        {peso(value)}
      </span>
    </div>
  );

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <Link href="/admin/reports" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-white mb-2">
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Reports
          </Link>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">COA Statement</p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">RPT Receivables</h1>
        </div>
        <div className="flex gap-3">
          <select
            value={year}
            onChange={(e) => setYear(e.target.value)}
            className="bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]/50"
          >
            {YEARS.map((y) => <option key={y} value={String(y)}>{y}</option>)}
          </select>
          <button
            onClick={fetchData}
            className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs uppercase tracking-wider rounded-xl border border-slate-700 transition-all"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button
            onClick={exportExcel}
            disabled={exporting || !data}
            className="flex items-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white font-bold text-xs uppercase tracking-wider rounded-xl transition-all"
          >
            <FileSpreadsheet className="w-4 h-4" /> {exporting ? "Exporting…" : "Export Excel"}
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
      ) : data ? (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl shadow-black/15">
          <div className="px-6 py-4 border-b border-slate-800 flex items-center gap-2">
            <Landmark className="w-5 h-5 text-[#4ca2ff]" />
            <h2 className="font-black text-sm text-white uppercase tracking-wider">
              Receivables Roll-Forward — {data.report_year}
            </h2>
          </div>
          <div className="divide-y divide-slate-800/60">
            <Row label="Beginning Receivable" value={data.beginning_receivable} />
            <Row label="Current-Year Assessment" value={data.current_year_assessment} sign="+" />
            <Row label="Collections" value={data.collections} sign="−" />
            <Row label="Adjustments" value={data.adjustments} sign="±" />
            <Row label="Ending Receivable" value={data.ending_receivable} bold />
          </div>
          <div className="px-6 py-3 border-t border-slate-800 text-xs text-slate-500">
            Ending = Beginning + Assessment − Collections + Adjustments
          </div>
        </div>
      ) : (
        !error && (
          <div className="py-16 text-center text-slate-500 font-bold bg-slate-900 border border-slate-800 rounded-2xl">
            No receivables data for {year}.
          </div>
        )
      )}
    </div>
  );
}
