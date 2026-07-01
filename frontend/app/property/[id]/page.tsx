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

/* ─── Design tokens (matched from reference screenshot) ─────────────────── */
const C = {
  heroBg:      "linear-gradient(135deg,#0a1628 0%,#0f2347 40%,#1a3a6b 70%,#0d2a4a 100%)",
  detailCard:  "#ffffff",           // white card in hero
  assessCard:  "linear-gradient(135deg,#1a7a8a 0%,#0d5f6e 100%)", // teal gradient
  pageBg:      "#eef2f7",           // light blue-gray page background
  statBg:      "#ffffff",
  navyDark:    "#0d1f3c",           // sidebar card
  teal:        "#367588",           // accent / help button
  tealLight:   "#5bb8cc",           // icon color in dark cards
  delinqText:  "#e05a2b",           // orange-red delinquent text
  delinqBg:    "#fff5f2",           // delinquent stat card bg
  delinqBorder:"#ffd5c8",
  paidGreen:   "#16a34a",
  paidBg:      "#f0fdf4",
  paidBorder:  "#bbf7d0",
  totalPaidTxt:"#1a3a6b",          // navy for total paid value
  lastPayTxt:  "#1a3a6b",          // navy for last payment value
};

function Skeleton() {
  return (
    <div className="animate-pulse bg-[#eef2f7] min-h-screen">
      <div className="h-56 bg-slate-300" />
      <div className="max-w-6xl mx-auto px-4 py-6 space-y-4">
        <div className="grid grid-cols-3 gap-4">
          {[...Array(3)].map((_,i) => <div key={i} className="h-24 bg-white rounded-2xl shadow-sm" />)}
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2 h-64 bg-white rounded-2xl shadow-sm" />
          <div className="h-64 bg-white rounded-2xl shadow-sm" />
        </div>
      </div>
    </div>
  );
}

export default function PropertyDetail() {
  const params   = useParams();
  const id       = params.id as string;
  const { toast } = useToast();

  const [data,     setData]     = useState<any>(null);
  const [history,  setHistory]  = useState<any[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState("");
  const [retrying, setRetrying] = useState(false);
  const [copied,   setCopied]   = useState(false);

  const load = async () => {
    setError("");
    try {
      const r = await fetch(`/api/public/property/${id}`, { cache: "no-store" });
      if (r.status === 404) { setError("Property not found. Check your TDN or PIN."); return; }
      if (r.status === 429) { setError("Too many requests. Please wait and try again."); return; }
      if (!r.ok)            { setError("Unable to load property data. Please try again."); return; }

      const text = await r.text();
      if (!text || !text.trim()) { setError("Server returned an empty response. Please try again."); return; }
      let json: any;
      try { json = JSON.parse(text); }
      catch { setError("Invalid response from server. Please try again."); return; }
      setData(json);

      try {
        const h = await fetch(`/api/public/property/${id}/history`, { cache: "no-store" });
        if (h.ok) {
          const ht = await h.text();
          if (ht && ht.trim()) setHistory(JSON.parse(ht));
        } else {
          toast("Payment history could not be loaded.", "info");
        }
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
    <div className="bg-[#eef2f7] min-h-screen flex items-center justify-center">
      <div className="text-center px-4">
        <AlertCircle className="w-12 h-12 text-red-400 mx-auto mb-4" />
        <h2 className="text-xl font-bold text-slate-800 mb-2">Could not load property</h2>
        <p className="text-slate-500 mb-6">{error}</p>
        <div className="flex justify-center gap-3">
          <button onClick={retry} disabled={retrying}
            className="flex items-center gap-2 px-5 py-2.5 text-white rounded-lg font-semibold text-sm disabled:opacity-50"
            style={{background:C.teal}}>
            <RefreshCw className={`w-4 h-4 ${retrying?"animate-spin":""}`} />
            {retrying ? "Retrying…" : "Try again"}
          </button>
          <Link href="/" className="flex items-center gap-2 px-5 py-2.5 bg-white text-slate-700 rounded-lg font-semibold text-sm border border-slate-200">
            <ArrowLeft className="w-4 h-4" /> New search
          </Link>
        </div>
      </div>
    </div>
  );

  const isDelinquent = data.status === "DELINQUENT";
  const isPending    = data.status === "PENDING";
  const isCompliant  = !isDelinquent && !isPending;
  const totalPaid    = history.reduce((s,p) => s + (p.amount||0), 0);
  const sorted       = [...history].sort((a,b) =>
    parseInt(String(b.period||"0")) - parseInt(String(a.period||"0")));

  // Phase 1: real computed figures from the backend (PropertyBilling-derived)
  const balance      = typeof data.balance === "number" ? data.balance : 0;
  const breakdown    = Array.isArray(data.billing_breakdown) ? data.billing_breakdown : [];
  const peso = (n: number) => "₱" + (n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2 });

  return (
    <div style={{background:C.pageBg}} className="min-h-screen">

      {/* ── HERO ─────────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden" style={{background:C.heroBg}}>

        {/* Municipal Hall photo — far right, very subtle */}
        <div className="absolute inset-0 flex justify-end pointer-events-none">
          <div className="relative w-1/3 h-full opacity-20">
            <Image src="/municipal-hall.png" alt="" fill className="object-cover object-center" priority />
            <div className="absolute inset-0" style={{background:"linear-gradient(to right,#0a1628 0%,transparent 60%)"}} />
          </div>
        </div>

        {/* Dot grid */}
        <div className="absolute inset-0 opacity-[0.035]"
          style={{backgroundImage:"radial-gradient(circle,#ffffff 1px,transparent 1px)",backgroundSize:"28px 28px"}} />

        <div className="relative max-w-6xl mx-auto px-4 sm:px-6 py-6">
          {/* Back to Search — above the glass panel */}
          <Link href="/" className="inline-flex items-center gap-1.5 text-sm mb-4 transition-colors px-4 py-2 rounded-full"
            style={{background:"rgba(255,255,255,0.15)", color:"rgba(255,255,255,0.85)", backdropFilter:"blur(8px)"}}>
            <ArrowLeft className="w-4 h-4" /> Back to Search
          </Link>

          {/* ── BIG GLASS PANEL ── */}
          <div className="rounded-3xl p-6"
            style={{
              background:"rgba(255,255,255,0.08)",
              backdropFilter:"blur(20px)",
              WebkitBackdropFilter:"blur(20px)",
              border:"1px solid rgba(255,255,255,0.15)",
              boxShadow:"0 8px 32px rgba(0,0,0,0.3)",
            }}>
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-stretch">

            {/* TD + status */}
            <div className="lg:col-span-5">
              {isDelinquent ? (
                <span className="inline-flex items-center gap-2 text-white text-xs font-bold px-3 py-1.5 rounded-full mb-3 uppercase tracking-wider"
                  style={{background:"#8b1a1a"}}>
                  <span className="w-1.5 h-1.5 rounded-full bg-red-300 animate-pulse" />
                  Payment Required
                </span>
              ) : isCompliant ? (
                <span className="inline-flex items-center gap-2 text-white text-xs font-bold px-3 py-1.5 rounded-full mb-3 uppercase tracking-wider"
                  style={{background:"#166534"}}>
                  <span className="w-1.5 h-1.5 rounded-full bg-green-300" />
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
                  {copied ? <Check className="w-3.5 h-3.5" style={{color:"#4ade80"}} /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? "Copied!" : "Copy TDN"}
                </button>
              </div>
              <p className="text-white/25 text-xs mt-3 uppercase tracking-widest">
                As of {new Date().toLocaleDateString("en-PH",{year:"numeric",month:"long",day:"numeric"})}
              </p>
            </div>

            {/* Property Details card — inside glass panel, semi-transparent */}
            <div className="lg:col-span-4 rounded-2xl p-5 h-full"
              style={{
                background:"rgba(255,255,255,0.12)",
                border:"1px solid rgba(255,255,255,0.18)",
              }}>
              <div className="flex items-center gap-2 mb-4">
                <FileText className="w-4 h-4 text-white/70" />
                <span className="font-bold text-white/80 text-sm">Property Details</span>
              </div>
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0"
                    style={{background:"rgba(255,255,255,0.15)"}}>
                    <Building2 className="w-4 h-4 text-white/80" />
                  </div>
                  <div>
                    <p className="text-white/50 text-[10px] uppercase tracking-wider font-semibold">Owner</p>
                    <p className="text-white font-bold text-sm">{data.owner_name}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0"
                    style={{background:"rgba(255,255,255,0.15)"}}>
                    <MapPin className="w-4 h-4 text-white/80" />
                  </div>
                  <div>
                    <p className="text-white/50 text-[10px] uppercase tracking-wider font-semibold">Location</p>
                    <p className="text-white font-bold text-sm">{data.location}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Assessed Value card — teal gradient with faint house icon */}
            <div className="lg:col-span-3 rounded-2xl p-5 text-white shadow-xl relative overflow-hidden h-full"
              style={{background:"linear-gradient(135deg,#1a7a8a 0%,#0d5f6e 100%)"}}>
              {/* Faint house watermark */}
              <div className="absolute bottom-2 right-3 opacity-10 text-8xl select-none pointer-events-none">🏠</div>
              <div className="relative">
                <div className="flex items-center gap-2 mb-3">
                  <Home className="w-4 h-4 text-white/60" />
                  <span className="text-white/60 text-xs font-bold uppercase tracking-widest">Assessed Value</span>
                </div>
                <p className="text-3xl font-black leading-tight">
                  ₱{data.assessed_value.toLocaleString("en-PH",{minimumFractionDigits:2})}
                </p>
                {data.assessment_as_of_year && (
                  <p className="text-white/55 text-[11px] mt-1">
                    Effective assessment as of {data.assessment_as_of_year}
                  </p>
                )}
                {data.future_assessment && (
                  <div className="mt-3 rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-xs">
                    <p className="text-white/60 uppercase tracking-wider font-semibold">Future assessment</p>
                    <p className="text-white font-bold mt-0.5">
                      ₱{Number(data.future_assessment.assessed_value || 0).toLocaleString("en-PH", {minimumFractionDigits:2})}
                      {" "}effective {data.future_assessment.effective_year}
                    </p>
                  </div>
                )}
                <span className="inline-flex items-center gap-1.5 bg-white/15 border border-white/20 px-2.5 py-1 rounded-full mt-3 text-xs font-bold text-white/80 uppercase">
                  <Home className="w-3 h-3" /> {data.kind}
                </span>
              </div>
            </div>

          </div>
          </div>{/* end glass panel */}
        </div>
      </div>

      {/* ── AMOUNT DUE — the answer to "how much do I owe?" ──────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 -mt-3 relative z-20">
        <div className="rounded-2xl shadow-lg p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-5"
          style={{
            background: isDelinquent ? "linear-gradient(135deg,#fff5f2 0%,#ffffff 60%)" : "linear-gradient(135deg,#f0fdf4 0%,#ffffff 60%)",
            border: `2px solid ${isDelinquent ? C.delinqBorder : C.paidBorder}`,
          }}>
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-2xl flex items-center justify-center flex-shrink-0"
              style={{background: isDelinquent ? "#ffe4dc" : C.paidBg}}>
              {isDelinquent
                ? <AlertCircle className="w-7 h-7" style={{color:C.delinqText}} />
                : <CheckCircle2 className="w-7 h-7" style={{color:C.paidGreen}} />}
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-widest"
                style={{color: isDelinquent ? C.delinqText : C.paidGreen}}>
                {isDelinquent ? "Amount Due" : isPending ? "Not Yet Billed" : "Fully Paid"}
              </p>
              <p className="text-4xl sm:text-5xl font-black leading-none mt-1"
                style={{color: isDelinquent ? C.delinqText : C.paidGreen}}>
                {isPending ? "—" : peso(balance)}
              </p>
              <p className="text-xs text-slate-400 mt-1.5">
                {isDelinquent
                  ? `Outstanding across ${breakdown.length} tax year(s) · as of ${data.as_of ?? ""}`
                  : isPending
                  ? "No billing records for this property yet"
                  : "No outstanding balance — your account is updated"}
              </p>
            </div>
          </div>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto">
            <Link href="/pay-guide"
              className="flex items-center justify-center gap-2 font-bold text-sm px-5 py-3 rounded-xl transition-opacity hover:opacity-90 whitespace-nowrap"
              style={{background:"#f5c518", color:"#1a1a2e"}}>
              How to Pay <ChevronRight className="w-4 h-4" />
            </Link>
            <a href={`/api/public/property/${encodeURIComponent(id)}/soa`} target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 font-bold text-sm px-5 py-3 rounded-xl border transition-colors whitespace-nowrap"
              style={{background:"#ffffff", color:C.teal, borderColor:C.teal}}>
              <FileText className="w-4 h-4" /> Download SOA
            </a>
          </div>
        </div>
      </div>

      {/* ── SECONDARY STATS ──────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">

          {/* Total Paid */}
          <div className="rounded-2xl shadow-sm border border-slate-100 p-5 flex items-center gap-4" style={{background:C.statBg}}>
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:C.paidBg}}>
              <CheckCircle2 className="w-6 h-6" style={{color:C.paidGreen}} />
            </div>
            <div>
              <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Total Paid</p>
              <p className="text-xl font-black" style={{color:C.totalPaidTxt}}>
                {peso(data.total_paid ?? totalPaid)}
              </p>
              <p className="text-xs text-slate-400">{history.length} payment(s) on record</p>
            </div>
          </div>

          {/* Total Billed */}
          <div className="rounded-2xl shadow-sm border border-slate-100 p-5 flex items-center gap-4" style={{background:C.statBg}}>
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:"#eff6ff"}}>
              <FileText className="w-6 h-6" style={{color:"#2563eb"}} />
            </div>
            <div>
              <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Total Billed</p>
              <p className="text-xl font-black" style={{color:C.totalPaidTxt}}>
                {peso(data.total_due ?? 0)}
              </p>
              <p className="text-xs text-slate-400">{breakdown.length} tax year(s)</p>
            </div>
          </div>

          {/* Last Payment */}
          <div className="rounded-2xl shadow-sm border border-slate-100 p-5 flex items-center gap-4" style={{background:C.statBg}}>
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:"#e8f4f7"}}>
              <Calendar className="w-6 h-6" style={{color:C.teal}} />
            </div>
            <div>
              <p className="text-xs text-slate-400 font-bold uppercase tracking-wider">Last Payment</p>
              <p className="text-xl font-black" style={{color:C.lastPayTxt}}>{data.last_payment?.period ?? sorted[0]?.period ?? "—"}</p>
              <p className="text-xs text-slate-400">{data.last_payment?.date_paid ?? sorted[0]?.date_paid ?? "No payments recorded"}</p>
            </div>
          </div>

        </div>
      </div>

      {/* ── BILLING BREAKDOWN (per-year) ─────────────────────────────────── */}
      {breakdown.length > 0 && (
        <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-2">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-6 py-4 flex items-center gap-2 border-b border-slate-100">
              <FileText className="w-4 h-4" style={{color:C.teal}} />
              <h2 className="font-bold text-slate-800">Billing Breakdown</h2>
              <span className="ml-auto text-xs text-slate-400">Basic + SEF + Penalty − Discount</span>
            </div>

            {/* Desktop table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100" style={{background:"#f8fafc"}}>
                    {["Year","Assessed","Basic","SEF","Penalty","Discount","Due","Paid","Balance"].map((h,i) => (
                      <th key={h} className={`px-4 py-3 text-xs font-bold text-slate-400 uppercase tracking-wider ${i===0?"text-left":"text-right"}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {breakdown.map((y:any) => (
                    <tr key={y.tax_year} className="border-b border-slate-50">
                      <td className="px-4 py-3 font-bold text-slate-800">{y.tax_year}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{peso(y.assessed_value)}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{peso(y.basic)}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{peso(y.sef)}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{peso(y.penalty)}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{peso(y.discount)}</td>
                      <td className="px-4 py-3 text-right font-semibold text-slate-700">{peso(y.total_due)}</td>
                      <td className="px-4 py-3 text-right text-slate-500">{peso(y.amount_paid)}</td>
                      <td className="px-4 py-3 text-right font-black"
                        style={{color: y.balance > 0 ? C.delinqText : C.paidGreen}}>
                        {peso(y.balance)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile cards */}
            <div className="sm:hidden divide-y divide-slate-100">
              {breakdown.map((y:any) => (
                <div key={y.tax_year} className="px-5 py-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-bold text-slate-800">{y.tax_year}</span>
                    <span className="font-black text-base" style={{color: y.balance > 0 ? C.delinqText : C.paidGreen}}>
                      {y.balance > 0 ? peso(y.balance) : "Paid"}
                    </span>
                  </div>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500">
                    <span>Basic: {peso(y.basic)}</span>
                    <span>SEF: {peso(y.sef)}</span>
                    <span>Penalty: {peso(y.penalty)}</span>
                    <span>Discount: {peso(y.discount)}</span>
                    <span className="text-slate-700 font-semibold">Due: {peso(y.total_due)}</span>
                    <span>Paid: {peso(y.amount_paid)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── MAIN CONTENT ─────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-10">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* Payment History */}
          <div className="lg:col-span-2 bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
            <div className="px-6 py-4 flex items-center justify-between border-b border-slate-100">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4" style={{color:C.teal}} />
                <h2 className="font-bold text-slate-800">Payment History</h2>
              </div>
              <span className="flex items-center gap-1.5 text-xs text-slate-400 bg-slate-50 border border-slate-100 px-3 py-1 rounded-full">
                <Calendar className="w-3 h-3" /> From 2023 onwards
              </span>
            </div>

            <div className="px-6 py-2.5 border-b flex items-start gap-2" style={{background:"#eff6ff",borderColor:"#dbeafe"}}>
              <span className="text-blue-400 text-sm flex-shrink-0 mt-0.5">ℹ</span>
              <p className="text-xs text-blue-700 leading-relaxed">
                Records shown are from <strong>January 2023</strong> onwards. For earlier transactions, visit the Municipal Treasury Office with your TDN and a valid ID.
              </p>
            </div>

            {sorted.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100" style={{background:"#f8fafc"}}>
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
                          <div className="w-0.5 h-7 rounded-full" style={{background:C.teal}} />
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
                        <span className="inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-full"
                          style={{background:C.paidBg, color:C.paidGreen, border:`1px solid ${C.paidBorder}`}}>
                          <CheckCircle2 className="w-3 h-3" /> Paid
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr style={{background:"#f8fafc",borderTop:"2px solid #e2e8f0"}}>
                    <td colSpan={3} className="px-5 py-3 text-xs font-bold text-slate-500 uppercase tracking-wider">Total Recorded</td>
                    <td className="px-5 py-3 text-right font-black" style={{color:C.paidGreen}}>
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
            <div className="rounded-2xl p-6 text-white" style={{background:"#1a3a8f"}}>
              {/* Header with headset icon */}
              <div className="flex items-start gap-4 mb-5">
                <div className="w-14 h-14 rounded-full flex items-center justify-center flex-shrink-0 mt-1"
                  style={{background:"#2d52b0"}}>
                  <Phone className="w-6 h-6 text-white" />
                </div>
                <div>
                  <p className="font-bold text-xl leading-snug text-white">
                    Need to pay or<br />correct your records?
                  </p>
                  <p className="text-sm leading-relaxed mt-2" style={{color:"#a8b8e8"}}>
                    Visit the Municipal Treasury Office — Doña Aurora St., North Pob., Dipaculao, Aurora 3203
                  </p>
                </div>
              </div>

              {/* Divider */}
              <div className="mb-5" style={{borderTop:"1px solid rgba(255,255,255,0.12)"}} />

              {/* Hours */}
              <div className="flex items-start gap-3 mb-6">
                <div className="w-8 h-8 rounded-full border-2 flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{borderColor:"rgba(255,255,255,0.35)"}}>
                  <Clock className="w-4 h-4" style={{color:"rgba(255,255,255,0.7)"}} />
                </div>
                <div>
                  <p className="text-white text-sm">Mon–Fri</p>
                  <p className="text-white font-bold text-lg leading-tight">8:00 AM – 5:00 PM</p>
                  <p className="text-sm" style={{color:"#a8b8e8"}}>Excluding holidays</p>
                </div>
              </div>

              {/* Yellow pill button */}
              <Link href="/help"
                className="flex items-center justify-between w-full font-bold text-base px-5 py-3.5 rounded-full hover:opacity-90 transition-opacity"
                style={{background:"#f5c518", color:"#1a1a2e"}}>
                <div className="flex items-center gap-3">
                  <div className="w-7 h-7 rounded-full border-2 flex items-center justify-center flex-shrink-0"
                    style={{borderColor:"rgba(26,26,46,0.5)"}}>
                    <span className="text-xs font-black" style={{color:"#1a1a2e"}}>💬</span>
                  </div>
                  Help &amp; Support
                </div>
                <ChevronRight className="w-5 h-5" />
              </Link>
            </div>

            <div className="rounded-2xl p-5" style={{background:"#fffbeb",border:"1px solid #fde68a"}}>
              <p className="font-bold text-sm mb-2 flex items-center gap-2" style={{color:"#92400e"}}>
                <span>💡</span> Payment Reminder
              </p>
              <p className="text-xs leading-relaxed" style={{color:"#78350f"}}>
                Pay before <strong>March 31</strong> for a <strong>10% discount</strong>. Advance payment earns <strong>20%</strong>. Late payments accrue <strong>2% monthly penalty</strong> from February 1.
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Footer note */}
      <div className="border-t py-4 text-center" style={{background:"#ffffff",borderColor:"#e2e8f0"}}>
        <p className="text-xs text-slate-400 flex items-center justify-center gap-2">
          🔒 Official Website — Municipal Treasury Office of Dipaculao, Aurora
        </p>
      </div>

    </div>
  );
}
