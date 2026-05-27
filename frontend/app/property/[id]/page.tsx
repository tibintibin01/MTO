"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, FileText, CheckCircle2, AlertCircle,
  Building2, MapPin, RefreshCw, Phone, Clock,
  Calendar, ChevronRight, Copy, Check,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { useToast } from "../../components/ToastProvider";

function PropertySkeleton() {
  return (
    <div className="animate-pulse">
      <div className="h-64 bg-slate-200" />
      <div className="max-w-6xl mx-auto px-4 py-8 grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="h-32 bg-slate-100 rounded-2xl" />
          <div className="h-48 bg-slate-100 rounded-2xl" />
        </div>
        <div className="h-64 bg-slate-100 rounded-2xl" />
      </div>
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
  const [copied, setCopied] = useState(false);

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

  const copyTDN = () => {
    if (data?.td_number) {
      navigator.clipboard.writeText(data.td_number);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

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
  const totalPaid    = history.reduce((s, p) => s + (p.amount || 0), 0);
  const sortedHistory = [...history].sort((a, b) =>
    parseInt(String(b.period || "0")) - parseInt(String(a.period || "0"))
  );

  return (
    <div className="flex flex-col min-h-screen bg-slate-50">

      {/* ── HERO ── */}
      <div className="relative overflow-hidden bg-[#0d1f3c]">
        {/* Geometric background pattern */}
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-0 right-0 w-96 h-96 bg-[#367588] rounded-full blur-3xl translate-x-1/2 -translate-y-1/2" />
          <div className="absolute bottom-0 left-1/3 w-64 h-64 bg-blue-400 rounded-full blur-3xl translate-y-1/2" />
          <div className="absolute top-1/2 left-0 w-48 h-48 bg-[#367588] rounded-full blur-2xl -translate-x-1/2" />
        </div>
        {/* Subtle grid overlay */}
        <div className="absolute inset-0 opacity-5"
          style={{ backgroundImage: "linear-gradient(#fff 1px,transparent 1px),linear-gradient(90deg,#fff 1px,transparent 1px)", backgroundSize: "40px 40px" }} />

        <div className="relative max-w-6xl mx-auto px-4 pt-5 pb-8">
          {/* Back link */}
          <Link href="/" className="inline-flex items-center gap-2 text-sm text-white/50 hover:text-white/90 mb-6 transition-colors group">
            <ArrowLeft className="w-4 h-4 group-hover:-translate-x-0.5 transition-transform" />
            Back to Search
          </Link>

          {/* Hero grid */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-start">

            {/* Left — TD + status */}
            <div className="lg:col-span-2">
              {/* Status pill */}
              <div className="mb-3">
                {isDelinquent ? (
                  <span className="inline-flex items-center gap-2 bg-red-500/15 border border-red-400/30 text-red-300 text-xs font-bold px-3 py-1.5 rounded-full uppercase tracking-widest">
                    <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                    Payment Required
                  </span>
                ) : isCompliant ? (
                  <span className="inline-flex items-center gap-2 bg-emerald-500/15 border border-emerald-400/30 text-emerald-300 text-xs font-bold px-3 py-1.5 rounded-full uppercase tracking-widest">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                    Account Updated
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-2 bg-white/10 border border-white/20 text-white/60 text-xs font-bold px-3 py-1.5 rounded-full uppercase tracking-widest">
                    Not Yet Billed
                  </span>
                )}
              </div>

              {/* TD Number */}
              <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight leading-none mb-2">
                {data.td_number}
              </h1>

              {/* PIN + copy */}
              <div className="flex items-center gap-3 mt-3">
                {data.pin && (
                  <span className="text-white/40 text-sm">PIN: {data.pin}</span>
                )}
                <button onClick={copyTDN}
                  className="flex items-center gap-1.5 text-xs text-white/40 hover:text-white/80 transition-colors">
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? "Copied" : "Copy TDN"}
                </button>
              </div>

              <p className="text-white/30 text-xs mt-4 uppercase tracking-widest">
                As of {new Date().toLocaleDateString("en-PH", { year: "numeric", month: "long", day: "numeric" })}
              </p>
            </div>

            {/* Middle — Property Details card */}
            <div className="lg:col-span-2 bg-white/10 backdrop-blur-sm border border-white/15 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <FileText className="w-4 h-4 text-white/50" />
                <p className="text-white/60 text-xs font-bold uppercase tracking-widest">Property Details</p>
              </div>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Building2 className="w-4 h-4 text-[#367588]" />
                  </div>
                  <div>
                    <p className="text-white/40 text-xs uppercase tracking-wider font-semibold">Owner</p>
                    <p className="text-white font-bold text-sm mt-0.5">{data.owner_name}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                    <MapPin className="w-4 h-4 text-[#367588]" />
                  </div>
                  <div>
                    <p className="text-white/40 text-xs uppercase tracking-wider font-semibold">Location</p>
                    <p className="text-white font-bold text-sm mt-0.5">{data.location}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Right — Assessed Value card */}
            <div className="lg:col-span-1 bg-gradient-to-br from-[#367588] to-[#2a5f70] rounded-2xl p-5 text-white flex flex-col justify-between min-h-[140px]">
              <div className="flex items-center gap-2 mb-2">
                <Building2 className="w-4 h-4 text-white/60" />
                <p className="text-white/60 text-xs font-bold uppercase tracking-widest">Assessed Value</p>
              </div>
              <div>
                <p className="text-2xl font-black leading-tight">
                  ₱{data.assessed_value.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
                </p>
                <span className="inline-flex items-center gap-1.5 bg-white/15 border border-white/20 px-2.5 py-1 rounded-full mt-3">
                  <div className="w-1.5 h-1.5 rounded-full bg-white/60" />
                  <span className="text-xs font-bold text-white/80 uppercase">{data.kind}</span>
                </span>
              </div>
            </div>

          </div>
        </div>
      </div>

      {/* ── STATS ROW ── */}
      <div className="bg-white border-b border-slate-100 shadow-sm">
        <div className="max-w-6xl mx-auto px-4">
          <div className="grid grid-cols-2 sm:grid-cols-3 divide-x divide-slate-100">

            <div className="px-6 py-4 flex items-center gap-4">
              <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center flex-shrink-0">
                <CheckCircle2 className="w-5 h-5 text-emerald-500" />
              </div>
              <div>
                <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Total Paid</p>
                <p className="text-lg font-black text-emerald-600">
                  ₱{totalPaid.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
                </p>
                <p className="text-xs text-slate-400">{history.length} payment(s) on record</p>
              </div>
            </div>

            <div className="px-6 py-4 flex items-center gap-4">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${isDelinquent ? "bg-red-50" : "bg-emerald-50"}`}>
                {isDelinquent
                  ? <AlertCircle className="w-5 h-5 text-red-500" />
                  : <CheckCircle2 className="w-5 h-5 text-emerald-500" />}
              </div>
              <div>
                <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Status</p>
                <p className={`text-lg font-black ${isDelinquent ? "text-red-500" : "text-emerald-600"}`}>
                  {isDelinquent ? "Delinquent" : isCompliant ? "Compliant" : "Pending"}
                </p>
                <p className="text-xs text-slate-400">{isDelinquent ? "Outstanding balance exists" : "No outstanding balance"}</p>
              </div>
            </div>

            <div className="px-6 py-4 flex items-center gap-4 col-span-2 sm:col-span-1">
              <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center flex-shrink-0">
                <Calendar className="w-5 h-5 text-[#367588]" />
              </div>
              <div>
                <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Last Payment</p>
                <p className="text-lg font-black text-slate-800">
                  {sortedHistory[0] ? sortedHistory[0].period : "—"}
                </p>
                <p className="text-xs text-slate-400">
                  {sortedHistory[0] ? sortedHistory[0].date_paid : "No payments recorded"}
                </p>
              </div>
            </div>

          </div>
        </div>
      </div>

      {/* ── MAIN CONTENT ── */}
      <div className="max-w-6xl mx-auto px-4 py-8 w-full grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left — Payment history */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">

            {/* Table header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#367588]" />
                <h2 className="font-bold text-slate-800">Payment History</h2>
              </div>
              <span className="text-xs text-slate-400 bg-slate-50 border border-slate-100 px-3 py-1 rounded-full flex items-center gap-1.5">
                <Calendar className="w-3 h-3" />
                From 2023 onwards
              </span>
            </div>

            {/* Disclaimer */}
            <div className="px-6 py-3 bg-blue-50/60 border-b border-blue-100/60 flex items-start gap-2">
              <span className="text-blue-400 text-sm mt-0.5 flex-shrink-0">ℹ</span>
              <p className="text-xs text-blue-700 leading-relaxed">
                Records shown are from <strong>January 2023</strong> onwards. For earlier transactions, visit the Municipal Treasury Office with your TDN and a valid ID.
              </p>
            </div>

            {sortedHistory.length > 0 ? (
              <>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-slate-50 border-b border-slate-100">
                      <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Period</th>
                      <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">OR Number</th>
                      <th className="px-6 py-3 text-left text-xs font-bold text-slate-400 uppercase tracking-wider">Date Paid</th>
                      <th className="px-6 py-3 text-right text-xs font-bold text-slate-400 uppercase tracking-wider">Amount</th>
                      <th className="px-6 py-3 text-center text-xs font-bold text-slate-400 uppercase tracking-wider">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedHistory.map((p, i) => (
                      <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/80 transition-colors group">
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <div className="w-1 h-8 rounded-full bg-[#367588] opacity-60 group-hover:opacity-100 transition-opacity" />
                            <span className="font-bold text-slate-800">{p.period}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-slate-500 font-mono text-xs">{p.or_number}</td>
                        <td className="px-6 py-4 text-slate-500 text-xs">{p.date_paid}</td>
                        <td className="px-6 py-4 text-right font-bold text-slate-800">
                          ₱{p.amount.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
                        </td>
                        <td className="px-6 py-4 text-center">
                          <span className="inline-flex items-center gap-1 bg-emerald-50 text-emerald-600 border border-emerald-100 text-xs font-bold px-2.5 py-1 rounded-full">
                            <CheckCircle2 className="w-3 h-3" /> Paid
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr className="bg-slate-50 border-t-2 border-slate-200">
                      <td colSpan={3} className="px-6 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider">Total Recorded</td>
                      <td className="px-6 py-3 text-right font-black text-emerald-600">
                        ₱{totalPaid.toLocaleString("en-PH", { minimumFractionDigits: 2 })}
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </>
            ) : (
              <div className="py-16 text-center">
                <FileText className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                <p className="text-slate-400 font-medium">No payment records found</p>
                <p className="text-slate-300 text-xs mt-1">Records available from January 2023 onwards</p>
              </div>
            )}
          </div>
        </div>

        {/* Right — Sidebar */}
        <div className="space-y-4">

          {/* Contact card */}
          <div className="bg-[#0d1f3c] rounded-2xl p-6 text-white">
            <p className="font-bold text-base mb-1">Need to pay or correct your records?</p>
            <p className="text-white/50 text-xs mb-5 leading-relaxed">
              Visit the Municipal Treasury Office to make payments, request certifications, or correct property information.
            </p>

            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                  <MapPin className="w-4 h-4 text-[#367588]" />
                </div>
                <div>
                  <p className="text-white/40 text-xs uppercase tracking-wider font-semibold mb-0.5">Address</p>
                  <p className="text-white/80 text-sm leading-relaxed">
                    Doña Aurora St., North Pob.<br />Dipaculao, Aurora 3203
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Clock className="w-4 h-4 text-[#367588]" />
                </div>
                <div>
                  <p className="text-white/40 text-xs uppercase tracking-wider font-semibold mb-0.5">Office Hours</p>
                  <p className="text-white/80 text-sm">Mon–Fri · 8:00 AM – 5:00 PM</p>
                  <p className="text-white/40 text-xs">Excluding holidays</p>
                </div>
              </div>
            </div>

            <Link href="/help"
              className="mt-6 w-full flex items-center justify-between bg-[#367588] hover:bg-[#2a5f70] transition-colors text-white font-bold text-sm px-4 py-3 rounded-xl">
              <div className="flex items-center gap-2">
                <Phone className="w-4 h-4" />
                Help &amp; Support
              </div>
              <ChevronRight className="w-4 h-4 opacity-60" />
            </Link>
          </div>

          {/* Quick tip card */}
          <div className="bg-amber-50 border border-amber-100 rounded-2xl p-5">
            <p className="font-bold text-amber-900 text-sm mb-2">💡 Payment Reminder</p>
            <p className="text-amber-800 text-xs leading-relaxed">
              Pay before <strong>March 31</strong> for a <strong>10% discount</strong>. Advance payment (prior year) earns a <strong>20% discount</strong>. Late payments accrue <strong>2% monthly penalty</strong> from February 1.
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}
