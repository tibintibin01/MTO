"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Landmark,
  Clock,
  MapPin,
  CreditCard,
  Building2,
  AlertTriangle,
  FileSpreadsheet,
  ArrowRight,
  AlertCircle,
} from "lucide-react";

// Reports that have a dedicated detail view
const VIEW_REPORTS = [
  {
    id: "receivables",
    title: "RPT Receivables Statement",
    description: "COA roll-forward: beginning, assessment, collections, ending receivable by year.",
    href: "/admin/reports/receivables",
    icon: Landmark,
    formats: "View · Excel",
  },
  {
    id: "aging",
    title: "Aging Report",
    description: "Outstanding receivables grouped into 30 / 60 / 90 / 120+ day buckets, by barangay.",
    href: "/admin/reports/aging",
    icon: Clock,
    formats: "View · CSV",
  },
  {
    id: "compliant",
    title: "Receivables by Barangay",
    description: "Per-barangay compliance and collection efficiency breakdown.",
    href: "/admin/compliant",
    icon: MapPin,
    formats: "View · CSV",
  },
];

// Reports exported directly as Excel via /billing/export/excel
const EXPORT_REPORTS = [
  {
    id: "collections",
    title: "Collections Report",
    description: "All posted payments with OR numbers, basic/SEF split, and totals.",
    icon: CreditCard,
    report_type: "collections",
  },
  {
    id: "delinquents",
    title: "Delinquent Accounts",
    description: "Every property with an outstanding balance and its arrears total.",
    icon: AlertTriangle,
    report_type: "delinquents",
  },
  {
    id: "assessment_roll",
    title: "Assessment Roll",
    description: "Full registry: TD number, owner, barangay, kind, assessed value.",
    icon: Building2,
    report_type: "assessment_roll",
  },
];

export default function ReportsHub() {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const exportExcel = async (reportType: string, label: string) => {
    setBusy(reportType);
    setError("");
    try {
      const res = await fetch("/api/v1/billing/export/excel", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify({ report_type: reportType, month: "All", year: "All" }),
      });
      if (res.status === 401) { window.location.href = "/admin/login"; return; }
      if (!res.ok) throw new Error("Export failed.");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `MTO_${reportType}_${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch {
      setError(`Could not export the ${label}. Please try again.`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      <div>
        <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Management & COA</p>
        <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Reports</h1>
        <p className="text-slate-400 text-sm mt-1">Standard treasury reports with on-screen views and exports.</p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 flex gap-3 text-sm text-red-300">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span className="font-bold flex-1">{error}</span>
        </div>
      )}

      {/* Interactive report views */}
      <div>
        <p className="text-[11px] font-black text-[#4ca2ff] uppercase tracking-widest mb-3">Interactive Reports</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {VIEW_REPORTS.map((r) => {
            const Icon = r.icon;
            return (
              <Link
                key={r.id}
                href={r.href}
                className="group bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-[#1f4e78]/60 transition-all flex flex-col"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="w-10 h-10 bg-[#1f4e78]/20 text-[#4ca2ff] rounded-xl flex items-center justify-center border border-[#1f4e78]/30">
                    <Icon className="w-5 h-5" />
                  </div>
                  <ArrowRight className="w-4 h-4 text-slate-600 group-hover:text-[#4ca2ff] transition-colors" />
                </div>
                <h3 className="font-bold text-white text-sm">{r.title}</h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed flex-1">{r.description}</p>
                <span className="text-[10px] font-extrabold text-slate-400 bg-slate-800 border border-slate-700 px-2 py-0.5 rounded-full uppercase mt-3 self-start">
                  {r.formats}
                </span>
              </Link>
            );
          })}
        </div>
      </div>

      {/* Direct Excel exports */}
      <div>
        <p className="text-[11px] font-black text-[#4ca2ff] uppercase tracking-widest mb-3">Excel Exports (COA)</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {EXPORT_REPORTS.map((r) => {
            const Icon = r.icon;
            return (
              <div key={r.id} className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex flex-col">
                <div className="w-10 h-10 bg-emerald-500/10 text-emerald-400 rounded-xl flex items-center justify-center border border-emerald-500/20 mb-3">
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="font-bold text-white text-sm">{r.title}</h3>
                <p className="text-xs text-slate-500 mt-1 leading-relaxed flex-1">{r.description}</p>
                <button
                  onClick={() => exportExcel(r.report_type, r.title)}
                  disabled={busy === r.report_type}
                  className="flex items-center justify-center gap-2 mt-4 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white font-bold text-xs uppercase tracking-wider rounded-xl transition-all"
                >
                  <FileSpreadsheet className="w-4 h-4" />
                  {busy === r.report_type ? "Exporting…" : "Export Excel"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
