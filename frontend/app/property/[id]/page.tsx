"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, FileText, CheckCircle2, AlertCircle,
  Building2, MapPin, RefreshCw, Phone, Calendar,
} from "lucide-react";
import Link from "next/link";
import { useToast } from "../../components/ToastProvider";

function PropertySkeleton() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-8 animate-pulse">
      <div className="h-4 w-28 bg-slate-200 rounded mb-8" />
      <div className="h-48 bg-slate-100 rounded-2xl mb-6" />
      <div className="grid grid-cols-3 gap-4 mb-8">
        {[...Array(3)].map((_, i) => <div key={i} className="h-24 bg-slate-100 rounded-xl" />)}
      </div>
      <div className="h-64 bg-slate-100 rounded-xl" />
    </div>
  );
}

export default function PropertyDetail() {
  const params = useParams();
  const id = params.id as string;
  const { toast } = useToast();

  const [data, setData] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);

  const fetchData = async () => {
    setError("");
    try {
      const res = await fetch(`/api/v1/public/property/${id}`);
      if (res.status === 404) { setError("Property not found. Please check your TDN or PIN."); return; }
      if (res.status === 429) { setError("Too many requests. Please wait a moment and try again."); return; }
      if (!res.ok) { setError("Unable to load property data. Please try again."); return; }
      const json = await res.json();
      setData(json);
      try {
        const hRes = await fetch(`/api/v1/public/property/${id}/history`);
        if (hRes.ok) setHistory(await hRes.json());
        else toast("Payment history could not be loaded.", "info");
      } catch { toast("Payment history is temporarily unavailable.", "info"); }
    } catch { setError("Network error. Please check your connection and try again."); }
    finally { setLoading(false); setRetrying(false); }
  };

  useEffect(() => { fetchData(); }, [id]);

  const handleRetry = () => { setLoading(true); setRetrying(true); fetchData(); };

  if (loading) return <PropertySkeleton />;

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-20 text-center">
        <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-6">
          <AlertCircle className="w-8 h-8 text-red-500" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">Could not load property</h2>
        <p className="text-slate-500 mb-8 max-w-sm mx-auto">{error}</p>
        <div className="flex items-center justify-center gap-3">
          <button onClick={handleRetry} disabled={retrying}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#1a3a6b] text-white rounded-lg font-semibold text-sm hover:bg-[#0f2a5e] transition-colors disabled:opacity-50">
            <RefreshCw className={`w-4 h-4 ${retrying ? "animate-spin" : ""}`} />
            {retrying ? "Retrying..." : "Try again"}
          </button>
          <Link href="/" className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-lg font-semibold text-sm hover:bg-slate-200 transition-colors">
            <ArrowLeft className="w-4 h-4" /> New search
          </Link>
        </div>
      </div>
    );
  }

  const isDelinquent = data.status === "DELINQUENT";
  const isPending    = data.status === "PENDING";
  const isCompliant  = !isDelinquent && !isPending;

  const totalPaid = history.reduce((s, p) => s + (p.amount || 0), 0);
  const sortedHistory = [...history].sort((a, b) =>
    parseInt(String(b.period || "0")) - parseInt(String(a.period || "0"))
  );

  return (
    <div className="flex flex-col min-h-screen bg-[#f0f4f8]">

      {/* ── Hero header — always dark blue, status shown as accent banner ── */}
      <div className="bg-gradient-to-r from-[#1a3a6b] via-[#1f4e78] to-[#1a3a6b] text-white">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <Link href="/" className="inline-flex items-center gap-2 text-sm text-white/70 hover:text-white mb-6 transition-colors">
            <ArrowLeft className="w-4 h-4" /> Back to Search
          </Link>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                {isDelinquent
                  ? <span className="bg-red-500/20 border border-red-400/40 text-red-300 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-widest flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                      Payment Required
                    </span>
                  : isCompliant
                  ? <span className="bg-green-500/20 border border-green-400/40 text-green-300 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-widest flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                      Account Updated
                    </span>
                  : <span className="bg-white/10 border border-white/20 text-white/60 text-xs font-bold px-3 py-1 rounded-full uppercase tracking-widest">
                      Not Yet Billed
                    </span>
                }
              </div>
              <h1 className="text-3xl sm:text-4xl font-black tracking-tight">{data.td_number}</h1>
              {data.pin && <p className="text-white/50 text-sm mt-1">PIN: {data.pin}</p>}
            </div>
            <div className="text-right">
              <p className="text-white/40 text-xs uppercase tracking-widest mb-1">As of</p>
              <p className="text-white font-bold">{new Date().toLocaleDateString("en-PH", { year: "numeric", month: "long", day: "numeric" })}</p>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 py-8 w-full flex-1">

        {/* ── Property info + assessed value ── */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
          <div className="sm:col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Property Details</p>
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Building2 className="w-4 h-4 text-[#1a3a6b]" />
                </div>
                <div>
                  <p className="text-xs text-slate-400 font-semibold uppercase">Owner</p>
                  <p className="text-slate-800 font-bold">{data.owner_name}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center flex-shrink-0">
                  <MapPin className="w-4 h-4 text-[#1a3a6b]" />
                </div>
                <div>
                  <p className="text-xs text-slate-400 font-semibold uppercase">Location</p>
                  <p className="text-slate-800 font-bold">{data.location}</p>
                </div>
              </div>
            </div>
          </div>

          <div className="bg-[#1a3a6b] rounded-2xl shadow-sm p-6 text-white flex flex-col justify-between">
            <p className="text-blue-200 text-xs font-bold uppercase tracking-widest">Assessed Value</p>
            <div>
              <p className="text-3xl font-black mt-2">
                ₱{data.assessed_value.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
              </p>
              <span className="inline-flex items-center gap-1.5 bg-white/10 border border-white/20 px-3 py-1 rounded-full mt-3">
                <div className="w-1.5 h-1.5 rounded-full bg-blue-300" />
                <span className="text-xs font-bold text-blue-100 uppercase">{data.kind}</span>
              </span>
            </div>
          </div>
        </div>

        {/* ── Stats row ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-6">
          <div className="bg-white rounded-xl border border-slate-100 shadow-sm p-5">
            <p className="text-xs text-slate-400 font-bold uppercase tracking-widest mb-1">Total Paid</p>
            <p className="text-xl font-black text-green-600">
              ₱{totalPaid.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
            </p>
            <p className="text-xs text-slate-400 mt-1">{history.length} payment(s) on record</p>
          </div>
          <div className={`rounded-xl border shadow-sm p-5 ${isDelinquent ? "bg-red-50 border-red-100" : "bg-green-50 border-green-100"}`}>
            <p className="text-xs font-bold uppercase tracking-widest mb-1 text-slate-400">Status</p>
            <div className={`flex items-center gap-2 ${isDelinquent ? "text-red-600" : "text-green-600"}`}>
              {isDelinquent
                ? <AlertCircle className="w-5 h-5" />
                : <CheckCircle2 className="w-5 h-5" />}
              <p className="text-base font-black">{isDelinquent ? "Delinquent" : isCompliant ? "Compliant" : "Pending"}</p>
            </div>
            <p className="text-xs text-slate-400 mt-1">{isDelinquent ? "Outstanding balance exists" : "No outstanding balance"}</p>
          </div>
          <div className="bg-white rounded-xl border border-slate-100 shadow-sm p-5 col-span-2 sm:col-span-1">
            <p className="text-xs text-slate-400 font-bold uppercase tracking-widest mb-1">Last Payment</p>
            <p className="text-base font-black text-slate-800">
              {sortedHistory[0] ? `${sortedHistory[0].period}` : "—"}
            </p>
            <p className="text-xs text-slate-400 mt-1">
              {sortedHistory[0] ? sortedHistory[0].date_paid : "No payments recorded"}
            </p>
          </div>
        </div>

        {/* ── Payment history ── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden mb-6">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <FileText className="w-4 h-4 text-[#1a3a6b]" />
            <h2 className="font-bold text-slate-800">Payment History</h2>
            <span className="ml-auto text-xs text-slate-400 bg-slate-50 border border-slate-100 px-2 py-1 rounded-full">
              From 2023 onwards
            </span>
          </div>

          <div className="px-6 py-3 bg-blue-50 border-b border-blue-100 flex items-start gap-2">
            <span className="text-blue-400 text-sm mt-0.5">ℹ</span>
            <p className="text-xs text-blue-700 leading-relaxed">
              Records shown are from <strong>January 2023</strong> onwards. For earlier transactions, visit the Municipal Treasury Office with your TDN and a valid ID.
            </p>
          </div>

          {sortedHistory.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-100">
                  <th className="px-6 py-3 text-left text-xs font-bold text-slate-500 uppercase tracking-wider">Period</th>
                  <th className="px-6 py-3 text-left text-xs font-bold text-slate-500 uppercase tracking-wider">OR Number</th>
                  <th className="px-6 py-3 text-left text-xs font-bold text-slate-500 uppercase tracking-wider">Date Paid</th>
                  <th className="px-6 py-3 text-right text-xs font-bold text-slate-500 uppercase tracking-wider">Amount</th>
                </tr>
              </thead>
              <tbody>
                {sortedHistory.map((p, i) => (
                  <tr key={i} className={`border-b border-slate-50 hover:bg-slate-50 transition-colors ${i % 2 === 0 ? "" : "bg-slate-50/50"}`}>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Calendar className="w-3.5 h-3.5 text-slate-300" />
                        <span className="font-bold text-[#1a3a6b]">{p.period}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-500 font-mono text-xs">{p.or_number}</td>
                    <td className="px-6 py-4 text-slate-500">{p.date_paid}</td>
                    <td className="px-6 py-4 text-right font-bold text-slate-800">
                      ₱{p.amount.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-slate-50 border-t-2 border-slate-200">
                  <td colSpan={3} className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider">Total Recorded</td>
                  <td className="px-6 py-3 text-right font-black text-green-600">
                    ₱{totalPaid.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
                  </td>
                </tr>
              </tfoot>
            </table>
          ) : (
            <div className="py-16 text-center">
              <FileText className="w-10 h-10 text-slate-200 mx-auto mb-3" />
              <p className="text-slate-400 font-medium">No payment records found</p>
              <p className="text-slate-300 text-xs mt-1">Records available from January 2023 onwards</p>
            </div>
          )}
        </div>

        {/* ── CTA ── */}
        <div className="bg-[#0f2a5e] rounded-2xl p-6 text-white flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-white/10 rounded-xl flex items-center justify-center flex-shrink-0">
              <Phone className="w-5 h-5 text-yellow-300" />
            </div>
            <div>
              <p className="font-bold">Need to pay or correct your records?</p>
              <p className="text-blue-200 text-sm">Visit the Municipal Treasury Office — Doña Aurora St., North Pob., Dipaculao, Aurora 3203</p>
              <p className="text-blue-300 text-xs mt-0.5">Mon–Fri · 8:00 AM – 5:00 PM · Excluding holidays</p>
            </div>
          </div>
          <Link href="/help"
            className="bg-yellow-400 text-[#0f2a5e] px-5 py-2.5 rounded-xl font-bold text-sm hover:bg-yellow-300 transition-colors whitespace-nowrap flex-shrink-0">
            Help & Support
          </Link>
        </div>

      </div>
    </div>
  );
}
