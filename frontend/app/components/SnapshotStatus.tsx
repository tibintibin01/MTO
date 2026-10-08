"use client";
import {useCallback,useEffect,useState} from "react";
import Link from "next/link";
import {formatPublishedAt,formatPublicationShort} from "../../lib/portalFreshness";

export function SnapshotStatus(){
  const [health,setHealth]=useState<any>(null),[pending,setPending]=useState(true),[failed,setFailed]=useState(false);
  const check=useCallback(async(signal:AbortSignal)=>{
    setPending(true);
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),12_000);
    const abort=()=>controller.abort();signal.addEventListener("abort",abort,{once:true});
    try{
      const response=await fetch("/api/health",{cache:"no-store",signal:controller.signal});
      const payload=await response.json();
      if(typeof payload.ok!=="boolean")throw new Error("Invalid readiness");
      if(!signal.aborted){setHealth(payload);setFailed(false);}
    }catch{if(!signal.aborted){setFailed(true);setHealth(null);}}
    finally{clearTimeout(timeout);signal.removeEventListener("abort",abort);if(!signal.aborted)setPending(false);}
  },[]);
  useEffect(()=>{
    let current=new AbortController();
    const refresh=()=>{current.abort();current=new AbortController();void check(current.signal);};
    refresh();const timer=setInterval(refresh,300_000);window.addEventListener("focus",refresh);
    return()=>{current.abort();clearInterval(timer);window.removeEventListener("focus",refresh);};
  },[check]);
  const ready=health?.ok===true;
  return <aside aria-label="Published record status" className={`portal-publication-status border-b px-4 py-3 text-sm ${ready?"border-slate-200 bg-slate-50 text-slate-700":"border-amber-300 bg-amber-50 text-amber-950"}`}>
    <div className="mx-auto max-w-6xl" role="status" aria-live="polite">
      {pending&&!health&&!failed?"Checking publication status…":ready?
        <p className="text-xs leading-5">Office records published: <strong>{formatPublicationShort(health.published_at)}</strong></p>:<>
          <p className="font-bold">{failed?"Publication status could not be checked.":health?.status==="stale"?"Published records are awaiting an update.":"Published records are temporarily unavailable."}</p>
          {health?.published_at&&<p>Last published: {formatPublishedAt(health.published_at)}.</p>}
          <p>Current financial figures must be confirmed with the office. <Link href="/help" className="font-semibold underline underline-offset-4">Get help</Link></p>
        </>}
    </div>
  </aside>;
}
