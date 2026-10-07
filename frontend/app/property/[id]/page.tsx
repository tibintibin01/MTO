"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import {
  ArrowLeft, FileText, CheckCircle2, AlertCircle,
  Building2, MapPin, RefreshCw, Phone, Clock,
  Calendar, ChevronDown, ChevronRight, Copy, Check, Home,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { useToast } from "../../components/ToastProvider";
import {formatPublishedAt,unavailableMessage} from "../../../lib/portalFreshness";
import {checkedHistory} from "../../../lib/publicHistory";
import {PAYMENT_GUIDANCE} from "../../../lib/publicGuidance";

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
  paidGreen:   "#15803d",
  paidBg:      "#f0fdf4",
  paidBorder:  "#bbf7d0",
  totalPaidTxt:"#1a3a6b",          // navy for total paid value
  lastPayTxt:  "#1a3a6b",          // navy for last payment value
};

const rise = {
  initial: { opacity: 0, y: 18 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.45, ease: "easeOut" as const },
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

export default function PropertyDetailPage() {
  return (
    <Suspense fallback={<Skeleton />}>
      <PropertyDetail />
    </Suspense>
  );
}

function PropertyDetail() {
  const params   = useParams();
  const searchParams = useSearchParams();
  const id       = params.id as string;
  const accountKey = (searchParams.get("account") || "").trim().toLowerCase();
  const accountQuery = accountKey ? `?account=${encodeURIComponent(accountKey)}` : "";
  const { toast } = useToast();

  const [data,     setData]     = useState<any>(null);
  const [history,  setHistory]  = useState<any[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState("");
  const [retrying, setRetrying] = useState(false);
  const [copied,   setCopied]   = useState(false);
  const [billingOpen, setBillingOpen] = useState(false);
  const [historyState,setHistoryState]=useState<"loading"|"ready"|"error">("loading");
  const [historyError,setHistoryError]=useState("");
  const [refresh,setRefresh]=useState(0);
  const [loadedFor,setLoadedFor]=useState("");
  const requestKey=id+accountQuery;

  useEffect(()=>{
    const controller=new AbortController();
    async function get(url:string){
      const child=new AbortController(),abort=()=>child.abort();
      controller.signal.addEventListener("abort",abort,{once:true});
      const timeout=setTimeout(abort,15_000);
      try{const response=await fetch(url,{cache:"no-store",signal:child.signal});return{response,payload:await response.json()};}
      finally{clearTimeout(timeout);controller.signal.removeEventListener("abort",abort);}
    }
    async function load(){
      setError("");setData(null);setHistory([]);setHistoryState("loading");setHistoryError("");setLoading(true);setLoadedFor("");
      try{
        const {response,payload}=await get(`/api/public/property/${encodeURIComponent(id)}${accountQuery}`);
        if(controller.signal.aborted)return;
        if(!response.ok){setError(unavailableMessage(payload,response.status===404?"Property not found. Check your TDN or PIN.":"Property data is temporarily unavailable. Please try again."));return;}
        if(!payload||typeof payload.td_number!=="string"||typeof payload.balance!=="number"||!Number.isFinite(payload.balance))throw new Error("Invalid property");
        setData(payload);setLoadedFor(requestKey);setLoading(false);
        try{
          const params=new URLSearchParams();if(accountKey)params.set("account",accountKey);if(payload.snapshot_id)params.set("snapshot",payload.snapshot_id);
          const suffix=params.size?"?"+params.toString():"";
          const h=await get(`/api/public/property/${encodeURIComponent(id)}/history${suffix}`);
          if(controller.signal.aborted)return;
          if(!h.response.ok){setHistoryState("error");setHistoryError(unavailableMessage(h.payload,"Payment history could not be loaded. Retry to refresh this account and its history."));return;}
          setHistory(checkedHistory(h.payload));setHistoryState("ready");
        }catch{if(!controller.signal.aborted){setHistoryState("error");setHistoryError("Payment history could not be loaded. Check your connection and retry.");}}
      }catch{if(!controller.signal.aborted)setError("The record could not be loaded. Check your connection and try again.");}
      finally{if(!controller.signal.aborted){setLoading(false);setRetrying(false);}}
    }
    void load();return()=>controller.abort();
  },[id,accountKey,accountQuery,requestKey,refresh]);

  const retry = () => {setRetrying(true);setRefresh(value=>value+1);};
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
        <p role="alert" className="text-slate-700 mb-6">{error}</p>
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

  if(!data||loadedFor!==requestKey)return <Skeleton/>;

  const isDelinquent = data.status === "DELINQUENT";
  const isPending    = data.status === "PENDING";
  const isCompliant  = !isDelinquent && !isPending;
  const totalPaid    = history.reduce((s,p) => s + (p.amount||0), 0);
  const sorted       = [...history].sort((a,b) =>
    parseInt(String(b.period||"0")) - parseInt(String(a.period||"0")));

  // Phase 1: real computed figures from the backend (PropertyBilling-derived)
  const balance      = typeof data.balance === "number" ? data.balance : 0;
  const totalCredit  = typeof data.total_credit === "number" ? data.total_credit : 0;
  const breakdown    = Array.isArray(data.billing_breakdown) ? data.billing_breakdown : [];
  const peso = (n: number) => "₱" + (n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2 });

  return (
    <div style={{background:C.pageBg}} className="min-h-screen">

      {/* ── HERO ─────────────────────────────────────────────────────────── */}
      <div className="relative overflow-hidden" style={{background:C.heroBg}}>

        {/* Municipal Hall photo — far right, very subtle */}
        <div className="absolute inset-0 flex justify-end pointer-events-none">
          <div className="relative w-1/3 h-full opacity-20">
            <Image src="/municipal-hall.png" alt="" fill sizes="33vw" quality={55} className="object-cover object-center" />
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
          <motion.div {...rise} className="rounded-3xl p-6 relative overflow-hidden"
            style={{
              background:"linear-gradient(145deg,rgba(255,255,255,0.13),rgba(255,255,255,0.055))",
              backdropFilter:"blur(20px)",
              WebkitBackdropFilter:"blur(20px)",
              border:"1px solid rgba(255,255,255,0.22)",
              boxShadow:"0 24px 70px rgba(0,8,28,0.42), inset 0 1px 0 rgba(255,255,255,0.18)",
            }}>
            <div className="absolute inset-x-10 top-0 h-px bg-gradient-to-r from-transparent via-amber-300/70 to-transparent" />
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
              <div className="flex items-center gap-4 text-blue-100 text-sm">
                {data.pin && <span>PIN: {data.pin}</span>}
                <button onClick={copy} className="flex items-center gap-1 hover:text-white/80 transition-colors text-xs">
                  {copied ? <Check className="w-3.5 h-3.5" style={{color:"#4ade80"}} /> : <Copy className="w-3.5 h-3.5" />}
                  {copied ? "Copied!" : "Copy TDN"}
                </button>
              </div>
              <p className="text-blue-100 text-xs mt-3 leading-5">
                Records published: {formatPublishedAt(data.published_at)}
              </p>
            </div>

            {/* Property Details card — inside glass panel, semi-transparent */}
            <motion.div whileHover={{ y: -3 }} transition={{ duration: 0.2 }} className="lg:col-span-4 rounded-2xl p-5 h-full"
              style={{
                background:"linear-gradient(145deg,rgba(255,255,255,0.18),rgba(255,255,255,0.08))",
                border:"1px solid rgba(255,255,255,0.24)",
                boxShadow:"0 14px 30px rgba(0,8,28,0.22), inset 0 1px 0 rgba(255,255,255,0.18)",
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
            </motion.div>

            {/* Assessed Value card — teal gradient with faint house icon */}
            <motion.div
              whileHover={{ y: -4, rotateX: 1.5, rotateY: -1.5 }}
              transition={{ duration: 0.2 }}
              className="lg:col-span-3 rounded-2xl p-5 text-white relative overflow-hidden h-full"
              style={{
                background:"linear-gradient(145deg,#238d9b 0%,#116b79 52%,#084955 100%)",
                boxShadow:"0 18px 38px rgba(0,25,38,0.38), inset 0 1px 0 rgba(255,255,255,0.24)",
                border:"1px solid rgba(147,235,240,0.24)",
                transformPerspective:900,
              }}>
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/60 to-transparent" />
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
            </motion.div>

          </div>
          </motion.div>{/* end glass panel */}
        </div>
      </div>

      {/* ── AMOUNT DUE — the answer to "how much do I owe?" ──────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 -mt-3 relative z-20">
        <motion.div
          {...rise}
          transition={{ duration: 0.45, delay: 0.08, ease: "easeOut" }}
          className="rounded-2xl p-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-5 relative overflow-hidden"
          style={{
            background: isDelinquent ? "linear-gradient(135deg,#fff5f2 0%,#ffffff 60%)" : "linear-gradient(135deg,#f0fdf4 0%,#ffffff 60%)",
            border: `2px solid ${isDelinquent ? C.delinqBorder : C.paidBorder}`,
            boxShadow:"0 18px 44px rgba(15,31,60,0.16), inset 0 1px 0 rgba(255,255,255,0.9)",
          }}>
          <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white to-transparent" />
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
              <p className="text-xs text-slate-600 mt-1.5">
                {isDelinquent
                  ? `Outstanding across ${breakdown.length} tax year(s) · as of ${data.as_of ?? ""}`
                  : isPending
                  ? "No billing records for this property yet"
                  : "No outstanding balance — your account is updated"}
              </p>
              {totalCredit > 0 && (
                <p className="text-xs font-semibold mt-2" style={{color:"#a16207"}}>
                  Unapplied credit: {peso(totalCredit)} · retained by tax year pending verification
                </p>
              )}
            </div>
          </div>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row gap-3 w-full sm:w-auto">
            <Link href="/pay-guide"
              className="flex items-center justify-center gap-2 font-bold text-sm px-5 py-3 rounded-xl transition-opacity hover:opacity-90 whitespace-nowrap"
              style={{background:"#f5c518", color:"#1a1a2e"}}>
              How to Pay <ChevronRight className="w-4 h-4" />
            </Link>
            <a href={`/api/public/property/${encodeURIComponent(id)}/soa${accountQuery}`} target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 font-bold text-sm px-5 py-3 rounded-xl border transition-colors whitespace-nowrap"
              style={{background:"#ffffff", color:C.teal, borderColor:C.teal}}>
              <FileText className="w-4 h-4" /> Download SOA
            </a>
          </div>
        </motion.div>
      </div>

      {/* ── SECONDARY STATS ──────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 py-5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">

          {/* Total Paid */}
          <motion.div whileHover={{ y: -4 }} transition={{ duration: 0.2 }} className="rounded-2xl border border-slate-200/80 p-5 flex items-center gap-4 relative overflow-hidden" style={{background:C.statBg,boxShadow:"0 10px 24px rgba(15,31,60,0.08), inset 0 1px 0 #fff"}}>
            <div className="absolute inset-x-0 top-0 h-1 bg-emerald-500" />
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:C.paidBg}}>
              <CheckCircle2 className="w-6 h-6" style={{color:C.paidGreen}} />
            </div>
            <div>
              <p className="text-xs text-slate-600 font-bold uppercase tracking-wider">Total Paid</p>
              <p className="text-xl font-black" style={{color:C.totalPaidTxt}}>
                {typeof data.total_paid==="number"?peso(data.total_paid):historyState==="ready"?peso(totalPaid):"Unavailable"}
              </p>
              <p className="text-xs text-slate-600">{historyState==="ready"?`${history.length} payment(s) on record`:historyState==="error"?"Payment history unavailable":"Loading payment history…"}</p>
            </div>
          </motion.div>

          {/* Total Billed */}
          <motion.div whileHover={{ y: -4 }} transition={{ duration: 0.2 }} className="rounded-2xl border border-slate-200/80 p-5 flex items-center gap-4 relative overflow-hidden" style={{background:C.statBg,boxShadow:"0 10px 24px rgba(15,31,60,0.08), inset 0 1px 0 #fff"}}>
            <div className="absolute inset-x-0 top-0 h-1 bg-blue-500" />
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:"#eff6ff"}}>
              <FileText className="w-6 h-6" style={{color:"#2563eb"}} />
            </div>
            <div>
              <p className="text-xs text-slate-600 font-bold uppercase tracking-wider">Total Billed</p>
              <p className="text-xl font-black" style={{color:C.totalPaidTxt}}>
                {peso(data.total_due ?? 0)}
              </p>
              <p className="text-xs text-slate-600">{breakdown.length} tax year(s)</p>
            </div>
          </motion.div>

          {/* Last Payment */}
          <motion.div whileHover={{ y: -4 }} transition={{ duration: 0.2 }} className="rounded-2xl border border-slate-200/80 p-5 flex items-center gap-4 relative overflow-hidden" style={{background:C.statBg,boxShadow:"0 10px 24px rgba(15,31,60,0.08), inset 0 1px 0 #fff"}}>
            <div className="absolute inset-x-0 top-0 h-1 bg-cyan-600" />
            <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0" style={{background:"#e8f4f7"}}>
              <Calendar className="w-6 h-6" style={{color:C.teal}} />
            </div>
            <div>
              <p className="text-xs text-slate-600 font-bold uppercase tracking-wider">Last Payment</p>
              <p className="text-xl font-black" style={{color:C.lastPayTxt}}>{data.last_payment?.period ?? sorted[0]?.period ?? "—"}</p>
              <p className="text-xs text-slate-600">{data.last_payment?.date_paid ?? sorted[0]?.date_paid ?? (historyState==="ready"?"No payments recorded":"History details unavailable")}</p>
            </div>
          </motion.div>

        </div>
      </div>

      {/* ── BILLING BREAKDOWN (per-year) ─────────────────────────────────── */}
      {breakdown.length > 0 && (
        <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-2">
          <div className="bg-white rounded-2xl border border-slate-200/80 overflow-hidden" style={{boxShadow:"0 10px 28px rgba(15,31,60,0.07)"}}>
            <button
              type="button"
              onClick={() => setBillingOpen((open) => !open)}
              aria-expanded={billingOpen}
              className={`w-full px-6 py-4 flex items-center gap-3 text-left transition-colors hover:bg-slate-50 ${billingOpen ? "border-b border-slate-100" : ""}`}
            >
              <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{background:"#e8f4f7"}}>
                <FileText className="w-4 h-4" style={{color:C.teal}} />
              </div>
              <div>
                <h2 className="font-bold text-slate-800">Billing Breakdown</h2>
                <p className="text-xs text-slate-600">{breakdown.length} tax year(s) · Basic + SEF + Penalty − Discount</p>
              </div>
              <div className="ml-auto flex items-center gap-3">
                <span className="text-sm font-black" style={{color:balance > 0 ? C.delinqText : C.paidGreen}}>
                  {balance > 0 ? `${peso(balance)} due` : "Fully paid"}
                </span>
                <ChevronDown className={`w-5 h-5 text-slate-600 transition-transform ${billingOpen ? "rotate-180" : ""}`} />
              </div>
            </button>

            {billingOpen && <>
            {/* Desktop table */}
            <div className="hidden sm:block overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100" style={{background:"#f8fafc"}}>
                    {["Year","Assessed","Basic","SEF","Penalty","Discount","Due","Paid","Credit","Balance"].map((h,i) => (
                      <th key={h} className={`px-4 py-3 text-xs font-bold text-slate-600 uppercase tracking-wider ${i===0?"text-left":"text-right"}`}>{h}</th>
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
                      <td className="px-4 py-3 text-right font-semibold" style={{color:y.credit > 0 ? "#a16207" : "#94a3b8"}}>
                        {peso(y.credit)}
                      </td>
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
                    <span style={{color:y.credit > 0 ? "#a16207" : undefined}}>Credit: {peso(y.credit)}</span>
                  </div>
                </div>
              ))}
            </div>
            </>}
          </div>
        </div>
      )}

      {/* ── MAIN CONTENT ─────────────────────────────────────────────────── */}
      <div className="max-w-6xl mx-auto px-4 sm:px-6 pb-10">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

          {/* Payment History */}
          <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-200/80 overflow-hidden" style={{boxShadow:"0 12px 30px rgba(15,31,60,0.08)"}}>
            <div className="flex flex-col gap-3 border-b border-slate-100 px-4 py-4 min-[440px]:flex-row min-[440px]:items-center min-[440px]:justify-between sm:px-6">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4" style={{color:C.teal}} />
                <h2 className="font-bold text-slate-800">Payment History</h2>
              </div>
              <span className="flex w-fit items-center gap-1.5 rounded-full border border-slate-100 bg-slate-50 px-3 py-1 text-xs text-slate-600">
                <Calendar className="w-3 h-3" /> From 2023 onwards
              </span>
            </div>

            <div className="flex items-start gap-2 border-b px-4 py-3 sm:px-6" style={{background:"#eff6ff",borderColor:"#dbeafe"}}>
              <span className="text-blue-400 text-sm flex-shrink-0 mt-0.5">ℹ</span>
              <p className="text-xs text-blue-700 leading-relaxed">
                Records shown are from <strong>January 2023</strong> onwards. For earlier transactions, visit the Municipal Treasury Office with your TDN and a valid ID.
              </p>
            </div>

            {historyState==="loading"?<p role="status" className="p-6 text-sm text-slate-700">Loading payment history…</p>:historyState==="error"?<div className="p-6">
              <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{historyError}</p>
              <button onClick={retry} disabled={retrying} className="mt-3 min-h-11 rounded-lg bg-blue-800 px-4 py-3 text-sm font-bold text-white disabled:opacity-60">Retry payment history</button>
              <p className="mt-2 text-xs text-slate-600">An unavailable history does not mean there are no payments.</p>
            </div>:sorted.length > 0 ? (
              <>
              <table className="hidden w-full text-sm sm:table">
                <thead>
                  <tr className="border-b border-slate-100" style={{background:"#f8fafc"}}>
                    {["Period","OR Number","Date Paid","Amount","Status"].map(h => (
                      <th key={h} className={`px-5 py-3 text-xs font-bold text-slate-600 uppercase tracking-wider ${h==="Amount"||h==="Status"?"text-right":"text-left"}`}>{h}</th>
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
                            <Calendar className="w-3.5 h-3.5 text-slate-600" />
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

              <div className="divide-y divide-slate-100 sm:hidden">
                {sorted.map((p, i) => (
                  <article key={i} className="px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="h-8 w-0.5 flex-shrink-0 rounded-full" style={{background:C.teal}} />
                        <Calendar className="h-4 w-4 flex-shrink-0 text-slate-600" />
                        <span className="truncate font-bold text-slate-800">{p.period}</span>
                      </div>
                      <span className="inline-flex flex-shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold"
                        style={{background:C.paidBg, color:C.paidGreen, border:`1px solid ${C.paidBorder}`}}>
                        <CheckCircle2 className="h-3 w-3" /> Paid
                      </span>
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-slate-100 pt-3">
                      <div className="min-w-0">
                        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">OR Number</p>
                        <p className="mt-1 truncate font-mono text-xs text-slate-600">{p.or_number}</p>
                      </div>
                      <div className="min-w-0 text-right">
                        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Date Paid</p>
                        <p className="mt-1 truncate text-xs text-slate-600">{p.date_paid}</p>
                      </div>
                      <div className="col-span-2 flex items-end justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2.5">
                        <p className="text-[10px] font-bold uppercase tracking-wider text-slate-600">Amount Paid</p>
                        <p className="text-base font-black text-slate-900">{peso(p.amount)}</p>
                      </div>
                    </div>
                  </article>
                ))}
                <div className="flex items-center justify-between gap-4 bg-slate-50 px-4 py-4">
                  <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Total Recorded</span>
                  <span className="text-base font-black" style={{color:C.paidGreen}}>{peso(totalPaid)}</span>
                </div>
              </div>
              </>
            ) : (
              <div className="py-14 text-center">
                <FileText className="w-10 h-10 text-slate-200 mx-auto mb-3" />
                <p className="text-slate-700 font-medium">No payment records found</p>
                <p className="text-slate-600 text-xs mt-1">Records available from January 2023 onwards</p>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-4">
            <motion.div whileHover={{ y: -3 }} transition={{ duration: 0.2 }} className="rounded-2xl p-6 text-white relative overflow-hidden" style={{background:"linear-gradient(145deg,#214aa9,#17377f 55%,#10285f)",boxShadow:"0 18px 38px rgba(16,40,95,0.26), inset 0 1px 0 rgba(255,255,255,0.2)",border:"1px solid rgba(255,255,255,0.12)"}}>
              <div className="absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white/60 to-transparent" />
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
            </motion.div>

            <div className="rounded-2xl p-5" style={{background:"#fffbeb",border:"1px solid #fde68a"}}>
              <p className="font-bold text-sm mb-2 flex items-center gap-2" style={{color:"#92400e"}}>
                <span>💡</span> Payment Reminder
              </p>
              <p className="text-xs leading-relaxed" style={{color:"#78350f"}}>
                {PAYMENT_GUIDANCE}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Footer note */}
      <div className="border-t py-4 text-center" style={{background:"#ffffff",borderColor:"#e2e8f0"}}>
        <p className="text-xs text-slate-600 flex items-center justify-center gap-2">
          🔒 Official Website — Municipal Treasury Office of Dipaculao, Aurora
        </p>
      </div>

    </div>
  );
}
