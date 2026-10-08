"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import {ArrowLeft,AlertCircle,RefreshCw} from "lucide-react";
import Link from "next/link";
import { useToast } from "../../components/ToastProvider";
import {unavailableMessage} from "../../../lib/portalFreshness";
import {checkedHistory} from "../../../lib/publicHistory";
import {PropertyWorkspace} from "../../components/PropertyWorkspace";

const C={teal:"#155d53"};

function Skeleton() {
  return (
    <div className="property-skeleton property-page min-h-screen" role="status" aria-label="Loading property record">
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
    <><noscript><p className="property-nojs">JavaScript is required to load a property record. <Link href="/help">Get assistance from the Treasury Office.</Link></p></noscript>
      <Suspense fallback={<Skeleton />}><PropertyDetail /></Suspense>
    </>
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
  const copy = async () => {
    if (!data?.td_number) return;
    try {
      await navigator.clipboard.writeText(data.td_number);
      setCopied(true); setTimeout(() => setCopied(false), 2000);
    } catch { toast("TDN could not be copied. Select the number and copy it manually.", "error"); }
  };

  if (loading) return <Skeleton />;

  if (error) return (
    <div className="property-page property-load-error min-h-screen flex items-center justify-center">
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

  return <PropertyWorkspace data={data} id={id} accountQuery={accountQuery} balance={balance}
    totalCredit={totalCredit} breakdown={breakdown} sorted={sorted} totalPaid={totalPaid}
    historyCount={history.length} isDelinquent={isDelinquent} isPending={isPending} isCompliant={isCompliant}
    historyState={historyState} historyError={historyError} retrying={retrying} copied={copied}
    billingOpen={billingOpen} onCopy={copy} onRetry={retry}
    onBillingToggle={()=>setBillingOpen(open=>!open)} peso={peso}/>;
}
