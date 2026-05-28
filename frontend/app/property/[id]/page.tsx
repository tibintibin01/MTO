"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft, FileText, CheckCircle2, AlertCircle,
  Building2, MapPin, RefreshCw, Phone, Clock,
  Calendar, ChevronRight, Copy, Check, Home,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { useToast } from "../../components/ToastProvider";

function Skeleton() {
  return (
    <div className="animate-pulse">
      <div className="h-56 bg-slate-200" />
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-4">
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_,i) => <div key={i} className="h-24 bg-slate-100 rounded-xl" />)}
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2 h-64 bg-slate-100 rounded-xl" />
          <div className="h-64 bg-slate-100 rounded-xl" />
        </div>
      </div>
    </div>
  );
}

export default function PropertyDetail() {
  const params  = useParams();
  const id      = params.id as string;
  const { toast } = useToast();

  const [data,    setData]    = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [retrying,setRetrying]= useState(false);
  const [copied,  setCopied]  = useState(false);

  const load = async () => {
    setError("");
    try {
      const r = await fetch(`/api/v1/public/property/${id}`);
      if (r.status === 404) { setError("Property not found. Check your TDN or PIN."); return; }
      if (r.status === 429) { setError("Too many requests. Please wait and try again."); return; }
      if (!r.ok)            { setError("Unable to load property data. Please try again."); return; }
      setData(await r.json());
      try {
        const h = await fetch(`/api/v1/public/property/${id}/history`);
        if (h.ok) setHistory(await h.json());
        else toast("Payment history could not be loaded.", "info");
      } catch { toast("Payment history temporarily unavailable.", "info"); }
    } catch { setError("Network error. Check your connection and try again."); }
    finally  { setLoading(false); setRetrying(false); }
  };

  useEffect(() => { load(); }, [id]);

  const retry = () => { setLoading(true); setRetrying(true); load(); };
  const copy  = () => {
    if (data?.td_number) {
      navigator.clipboard.writeText(data.td_number);
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) return <Skeleton />;

  if (error) return (
    <div className="max-w-4xl mx-auto px-4 py-20 text-center">
      <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
      <h2 className="text-xl font-bold text-slate-800 mb-2">Could not load property</h2>
      <p className="text-slate-500 mb-6">{error}</p>
      <div className="flex justify-center gap-3">
        <button onClick={retry} disabled={retrying}
          className="flex items-center gap-2 px-5 py-2.5 bg-[#1a3a6b] text-white rounded-lg font-semibold text-sm disabled:opacity-50">
          <RefreshCw className={`w-4 h-4 ${retrying?"animate-spin":""}`} />
          {retrying ? "Retrying…" : "Try again"}
        </button>
        <Link href="/" className="flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-lg font-semibold text-sm">
          <ArrowLeft className="w-4 h-4" /> New search
        </Link>
      </div>
    </div>
  );

  const isDelinquent = data.status === "DELINQUENT";
  const isPending    = data.status === "PENDING";
  const isCompliant  = !isDelinquent && !isPending;
  const totalPaid    = history.reduce((s,p) => s + (p.amount||0), 0);
  const sorted       = [...history].sort((a,b) =>
    parseInt(String(b.period||"0")) - parseInt(String(a.period||"0")));

  return (
    <div className="bg-slate-100 min-h-screen">

      {/* ── HERO ─────────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden" style={{background:"linear-gradient(135deg,#0d1f3c 0%,#1a3a6b 45%,#1e4d7a 60%,#0d2a4a 100%)"}}>

        {/* Building photo — right side, faded */}
        <div className="absolute inset-0 flex justify-end">
          <div className="relative w-1/2 h-full opacity-20">
            <Image src="/municipal-hall.jpg" alt="" fill className="object-cover object-center" />
            <div className="absolute inset-0 bg-gradient-to-r from-[#0d1f3c] via-[#0d1f3c]/60 to-transparent" />
          </div>
        </div>

        {/* Subtle dot grid */}
        <div className="absolute inset-0 opacity-[0.04]"
          style={{backgroundImage:"radial-gradient(circle,#fff 1px,transparent 1px)",backgroundSize:"28px 28px"}} />

        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-6">

          {/* Back */}
          <Link href="/" className="inline-flex items-center gap-1.5 text-white/50 hover:text-white text-sm mb-5 transition-colors">
            <ArrowLeft className="w-4 h-4" /> Back to Search
          </Link>

          {/* 3-column hero grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">

            {/* Col 1 — TD + status (5 cols) */}
            <div className="lg:col-span-5">
              {/* Status pill */}
              {isDelinquent ? (
                <span className="inline-flex items-center gap-2 bg-red-600/80 text-white text-xs font-bold px-3 py-1.5 rounded-full mb-3 uppercase tracking-wider">
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  Payment Required
                </span>
              ) : isCompliant ? (
                <span className="inline-flex items-center gap-2 bg-emerald-600/80 text-white text-xs font-bold px-3 py-1.5 rounded-full mb-3 uppercase tracking-wider">
                  <span className="w-1.5 h-1.5 rounded-full bg-white" />
                  Account Updated
                </span>
              ) : (
                <span className="inline-flex items-center gap-2 bg-white/15 text-white/70 text-xs font-bold px-3 py-1.5 rounded-full mb-3 uppercase tracking-wider">
                  Not Yet Billed
                </span>
              )}

              <h1 className="text-4xl sm:text-5xl font-black text-white tracking-tight leading-none mb-3">
                {data.td_number}
              </h1>

              <div className="flex items-center gap-4 text-white/40 text-sm">
                {data.pin && <span>PIN: {data.pin}</span>}
                <button onClick={copy} className="flex items-center gap-1 hover:text-white/80 transition-colors text-xs">
                  {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? "Copied!" : "Copy TDN"}
                </button>
              </div>
              <p className="text-white/25 text-xs mt-3 uppercase tracking-widest">
                As of {new Date().toLocaleDateString("en-PH",{year:"numeric",month:"long",day:"numeric"})}
              </p>
            </div>

            {/* Col 2 — Property Details card (4 cols) */}
            <div className="lg:col-span-4 bg-white/10 backdrop-blur-md border border-white/15 rounded-2xl p-5">
              <div className="flex items-center gap-2 mb-4">
                <FileText className="w-4 h-4 text-white/40" />
                <span className="text-white/50 text-xs font-bold uppercase tracking-widest">Property Details</span>
              </div>
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center flex-shrink-0">
                    <Building2 className="w-4 h-4 text-[#5bb8cc]" />
                  </div>
                  <div>
                    <p className="text-white/40 text-[10px] uppercase tracking-wider font-semibold">Owner</p>
                    <p className="text-white font-bold text-sm">{data.owner_name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-lg bg-white/10 flex items-center justify-center flex-shrink-0">
                    <MapPin className="w-4 h-4 text-[#5bb8cc]" />
                  </div>
                  <div>
                    <p className="text-white/40 text-[10px] uppercase tracking-wider font-semibold">Location</p>
                    <p className="text-white font-bold text-sm">{data.location}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Col 3 — Assessed Value card (3 cols) */}
            <div className="lg:col-span-3 bg-gradient-to-br from-[#367588] to-[#1e5a6e] rounded-2xl p-5 text-white">
              <div className="flex items-center gap-2 mb-3">
                <Home className="w-4 h-4 text-white/60" />
                <span className="text-white/60 text-xs font-bold uppercase tracking-widest">Assessed Value</span>
              </div>
              <p className="text-3xl font-black leading-tight">
                ₱{data.assessed_value.toLocaleString("en-PH",{minimumFractionDigits:2})}
              </p>
              <span className="inline-flex items-center gap-1.5 bg-white/15 border border-white/20 px-2.5 py-1 rounded-full mt-3 text-xs font-bold text-white/80 uppercase">
                <Home className="w-3 h-3" /> {data.kind}
              </span>
            </div>

          </div>
        </div>
      </div>

      {/* ── STAT CARDS ───────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 -mt-0 py-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">

          {/* Total Paid */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 flex items-center gap-4">
            <div className="w-12 h-12 bg-emerald-50 rounded-xl flex items-center justify-center flex-shrink-0">
              <CheckCircle2 className="w-6 h-6 text-emerald-500" />
            </div>
            <div>
              <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Total Paid</p>
              <p className="text-xl font-black text-emerald-600">
                ₱{totalPaid.toLocaleString("en-PH",{minimumFractionDigits:2})}
              </p>
              <p className="text-xs text-slate-400">{history.length} payment(s) on record</p>
            </div>
          </div>

          {/* Status */}
          <div className={`bg-white rounded-2xl shadow-sm border p-5 flex items-center gap-4 ${isDelinquent?"border-red-100":"border-slate-100"}`}>
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 ${isDelinquent?"bg-red-50":"bg-emerald-50"}`}>
              {isDelinquent
                ? <AlertCircle className="w-6 h-6 text-red-500" />
                : <CheckCircle2 className="w-6 h-6 text-emerald-500" />}
            </div>
            <div>
              <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Status</p>
              <p className={`text-xl font-black ${isDelinquent?"text-red-500":"text-emerald-600"}`}>
                {isDelinquent ? "Delinquent" : isCompliant ? "Compliant" : "Pending"}
              </p>
              <p className="text-xs text-slate-400">{isDelinquent?"Outstanding balance exists":"No outstanding balance"}</p>
            </div>
          </div>

          {/* Last Payment */}
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 flex items-center gap-4">
            <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center flex-shrink-0">
              <Calendar className="w-6 h-6 text-[#367588]" />
            </div>
            <div>
              <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Last Payment</p>
              <p className="text-xl font-black text-slate-800">{sorted[0]?.period ?? "—"}</p>
              <p className="text-xs text-slate-400">{sorted[0]?.date_paid ?? "No payments recorded"}</p>
            </div>
          </div>

        </div>
      </div>

      {/* ── MAIN CONTENT ─────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-10">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* Payment History */}
          <div className="lg:col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-6 py-4 flex items-center justify-between border-b border-slate-100">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#367588]" />
                <h2 className="font-bold text-slate-800">Payment History</h2>
              </div>
              <span className="flex items-center gap-1.5 text-xs text-slate-400 bg-slate-50 border border-slate-100 px-3 py-1 rounded-full">
                <Calendar className="w-3 h-3" /> From 2023 onwards
              </span>
            </div>

            <div className="px-6 py-2.5 bg-blue-50/70 border-b border-blue-100/60 flex items-start gap-2">
              <span className="text-blue-400 text-sm flex-shrink-0 mt-0.5">ℹ</span>
              <p className="text-xs text-blue-700 leading-relaxed">
                Records shown are from <strong>January 2023</strong> onwards. For earlier transactions, visit the Municipal Treasury Office with your TDN and a valid ID.
              </p>
            </div>

            {sorted.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    {["Period","OR Number","Date Paid","Amount","Status"].map(h => (
                      <th key={h} className={`px-5 py-3 text-xs font-bold text-slate-400 uppercase tracking-wider ${h==="Amount"||h==="Status"?"text-right":"text-left"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((p,i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/80 transition-colors">
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2">
                          <div className="w-0.5 h-7 rounded-full bg-[#367588]" />
                          <div className="flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-slate-300" />
                            <span className="font-bold text-slate-800">{p.period}</span>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3.5 font-mono text-xs text-slate-500">{p.or_number}</td>
                      <td className="px-5 py-3.5 text-xs text-slate-500">{p.date_paid}</td>
                      <td className="px-5 py-3.5 text-right font-bold text-slate-800">
                        ₱{p.amount.toLocaleString("en-PH",{minimumFractionDigits:2})}
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        <span className="inline-flex items-center gap-1 bg-emerald-50 text-emerald-600 border border-emerald-100 text-xs font-bold px-2.5 py-1 rounded-full">
                          <CheckCircle2 className="w-3 h-3" /> Paid
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="bg-slate-50 border-t-2 border-slate-200">
                    <td colSpan={3} className="px-5 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider">Total Recorded</td>
                    <td className="px-5 py-3 text-right font-black text-emerald-600">
                      ₱{totalPaid.toLocaleString("en-PH",{minimumFractionDigits:2})}
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            ) : (
              <div className="py-14 text-center">
                <FileText className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                <p className="text-slate-400 font-medium">No payment records found</p>
                <p className="text-slate-300 text-xs mt-1">Records available from January 2023 onwards</p>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-4">

            {/* Contact card */}
            <div className="bg-[#0d1f3c] rounded-2xl p-6 text-white">
              <p className="font-bold text-base mb-1 leading-snug">Need to pay or correct your records?</p>
              <p className="text-white/40 text-xs mb-5 leading-relaxed">
                Visit the Municipal Treasury Office to make payments, request certifications, or correct property information.
              </p>
              <div className="space-y-4 mb-5">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0">
                    <MapPin className="w-4 h-4 text-[#5bb8cc]" />
                  </div>
                  <div>
                    <p className="text-white/40 text-[10px] uppercase tracking-wider font-bold mb-0.5">Address</p>
                    <p className="text-white/80 text-xs leading-relaxed">Doña Aurora St., North Pob.<br />Dipaculao, Aurora 3203</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Clock className="w-4 h-4 text-[#5bb8cc]" />
                  </div>
                  <div>
                    <p className="text-white/40 text-[10px] uppercase tracking-wider font-bold mb-0.5">Office Hours</p>
                    <p className="text-white/80 text-xs">Mon–Fri · 8:00 AM – 5:00 PM</p>
                    <p className="text-white/30 text-[10px]">Excluding holidays</p>
                  </div>
                </div>
              </div>
              <Link href="/help"
                className="flex items-center justify-between w-full bg-[#367588] hover:bg-[#2a5f70] transition-colors text-white font-bold text-sm px-4 py-3 rounded-xl">
                <div className="flex items-center gap-2">
                  <Phone className="w-4 h-4" />
                  Help &amp; Support
                </div>
                <ChevronRight className="w-4 h-4 opacity-60" />
              </Link>
            </div>

            {/* Payment reminder */}
            <div className="bg-amber-50 border border-amber-100 rounded-2xl p-5">
              <p className="font-bold text-amber-900 text-sm mb-2 flex items-center gap-2">
                <span>💡</span> Payment Reminder
              </p>
              <p className="text-amber-800 text-xs leading-relaxed">
                Pay before <strong>March 31</strong> for a <strong>10% discount</strong>. Advance payment earns <strong>20%</strong>. Late payments accrue <strong>2% monthly penalty</strong> from February 1.
              </p>
            </div>

          </div>
        </div>
      </div>

      {/* ── FOOTER NOTE ──────────────────────────────────────────────────── */}
      <div className="border-t border-slate-200 bg-white py-4 text-center">
        <p className="text-xs text-slate-400 flex items-center justify-center gap-2">
          <span className="w-4 h-4 border border-slate-300 rounded-full flex items-center justify-center text-[10px]">🔒</span>
          Official Website — Municipal Treasury Office of Dipaculao, Aurora
        </p>
      </div>

    </div>
  );
}
