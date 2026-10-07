"use client";

import {useEffect,useRef,useState} from "react";
import {useRouter} from "next/navigation";
import Image from "next/image";
import Link from "next/link";
import {AlertCircle,ArrowRight,CalendarDays,FileText,Landmark,Search,Shield} from "lucide-react";
import {unavailableMessage} from "../lib/portalFreshness";
import {PAYMENT_GUIDANCE} from "../lib/publicGuidance";

const QUERY_PATTERN=/^[A-Za-z0-9][A-Za-z0-9\-./# ]{1,49}$/;
type Match={account_key:string;owner_name:string;pin:string|null;barangay:string|null;location:string|null;kind:string|null};
async function readResponse(url:string){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),15_000);
  try{const response=await fetch(url,{cache:"no-store",signal:controller.signal});return{response,payload:await response.json()};}
  finally{clearTimeout(timeout);}
}
export default function Home(){
  const router=useRouter();
  const [interactive,setInteractive]=useState(false);
  useEffect(()=>setInteractive(true),[]);
  const [query,setQuery]=useState(""),[error,setError]=useState(""),[loading,setLoading]=useState(false);
  const [matches,setMatches]=useState<Match[]>([]),[showFind,setShowFind]=useState(false);
  const [findName,setFindName]=useState(""),[barangay,setBarangay]=useState(""),[findLoading,setFindLoading]=useState(false);
  const [findError,setFindError]=useState(""),[findMessage,setFindMessage]=useState(""),[findResults,setFindResults]=useState<any[]>([]);
  const searchPending=useRef(false),findPending=useRef(false);
  async function handleSearch(e:React.FormEvent){
    e.preventDefault();if(searchPending.current)return;setError("");setMatches([]);
    const value=query.trim();
    if(!QUERY_PATTERN.test(value)){setError(value?"Check the TDN or PIN printed on your document.":"Enter a Tax Declaration Number or PIN.");return;}
    searchPending.current=true;setLoading(true);
    try{
      const{response,payload}=await readResponse("/api/public/property/"+encodeURIComponent(value));
      if(response.status===404){setError("No property found. Check the identifier or contact the office for assistance.");return;}
      if(response.status===409&&payload.code==="MULTIPLE_PROPERTY_ACCOUNTS"&&Array.isArray(payload.matches)&&payload.matches.length>1){setMatches(payload.matches);return;}
      if(!response.ok){setError(unavailableMessage(payload,"Property search is temporarily unavailable. Please try again or contact the office."));return;}
      router.push("/property/"+encodeURIComponent(value));
    }catch{setError("The search could not finish. Check your connection and try again.");}
    finally{setLoading(false);searchPending.current=false;}
  }
  async function handleFind(e:React.FormEvent){
    e.preventDefault();if(findPending.current)return;setFindError("");setFindMessage("");setFindResults([]);
    if(findName.trim().length<3){setFindError("Enter at least three characters of the owner's name.");return;}
    findPending.current=true;setFindLoading(true);
    try{
      const params=new URLSearchParams({name:findName.trim()});if(barangay.trim())params.set("barangay",barangay.trim());
      const{response,payload}=await readResponse("/api/public/find?"+params);
      if(!response.ok){setFindError(unavailableMessage(payload,payload.detail||"Owner search is temporarily unavailable."));return;}
      if(payload.too_many){setFindMessage("Too many matches. Add the barangay or more of the owner's name.");return;}
      if(!Array.isArray(payload.results))throw new Error("Invalid results");
      if(!payload.results.length){setFindMessage("No matching properties found. Check the spelling or contact the office.");return;}
      setFindResults(payload.results);
    }catch{setFindError("The search could not finish. Check your connection and try again.");}
    finally{setFindLoading(false);findPending.current=false;}
  }
  return <div>
    <section className="relative isolate overflow-hidden bg-[#061832] px-4 py-8 text-white sm:py-12">
      <Image src="/municipal-hall.png" alt="" fill sizes="100vw" quality={55} className="-z-20 object-cover opacity-20"/>
      <div className="absolute inset-0 -z-10 bg-gradient-to-r from-[#061832]/95 to-[#173d70]/90" aria-hidden="true"/>
      <div className="mx-auto max-w-3xl">
        <h1 className="text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl">Real Property Tax <span className="text-yellow-300">Inquiry</span></h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-blue-100 sm:text-base">Look up published property records using the TDN or PIN on your document.</p>
        {!interactive&&<p className="mt-4 rounded-lg bg-amber-100 p-3 text-sm text-amber-950">JavaScript is required for property lookup. If this message stays visible, enable it or <a href="/help" className="underline">contact the Treasury Office for assistance.</a></p>}
        <form onSubmit={handleSearch} action="/help" className="mt-6 rounded-2xl bg-white p-4 text-slate-900 shadow-lg sm:p-5" aria-busy={loading}>
          <label htmlFor="property-query" className="block text-sm font-bold">Tax Declaration Number or PIN</label>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <input id="property-query" type="text" value={query} disabled={!interactive||loading} maxLength={50}
              onChange={e=>{setQuery(e.target.value);setError("");setMatches([]);}}
              aria-invalid={!!error} aria-describedby={error?"property-query-help property-query-error":"property-query-help"}
              autoComplete="off" spellCheck={false} placeholder="e.g. 06-0012-01379"
              className="min-w-0 flex-1 rounded-lg border border-slate-400 px-3 py-3 text-base placeholder:text-slate-600 disabled:bg-slate-100"/>
            <button type="submit" disabled={!interactive||loading} className="flex min-h-12 items-center justify-center gap-2 rounded-lg bg-blue-800 px-5 py-3 text-sm font-bold text-white hover:bg-blue-900 disabled:opacity-60"><Search aria-hidden="true" className="h-4 w-4"/>{loading?"Searching…":"Search property"}</button>
          </div>
          <p id="property-query-help" className="mt-2 text-xs leading-5 text-slate-600">Find your TDN on a tax declaration or receipt. Your PIN is the property identifier, not a password.</p>
          {error&&<p id="property-query-error" role="alert" className="mt-3 flex gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-800"><AlertCircle aria-hidden="true" className="h-5 w-5 shrink-0"/>{error}</p>}
          {matches.length>0&&<section aria-label="Matching property accounts" className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3">
            <h2 className="font-bold">{matches.length} separate accounts use this identifier</h2><p className="mt-1 text-sm">Choose the correct property. Billing and history remain separate.</p>
            <div className="mt-3 space-y-2">{matches.map(match=><button key={match.account_key} type="button"
              onClick={()=>router.push("/property/"+encodeURIComponent(query.trim())+"?account="+encodeURIComponent(match.account_key))}
              className="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-300 bg-white p-3 text-left hover:bg-blue-50">
              <span><span className="block font-bold">{match.owner_name}</span><span className="text-xs text-slate-700">{match.barangay||match.location||"Location unavailable"} · {match.kind||"Property"}{match.pin?" · PIN "+match.pin:""}</span></span><span className="font-semibold text-blue-800">Select →</span>
            </button>)}</div>
          </section>}
        </form>
        <button type="button" disabled={!interactive} onClick={()=>setShowFind(v=>!v)} aria-expanded={showFind} aria-controls="owner-finder"
          className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-lg px-2 text-sm font-semibold text-yellow-200 underline underline-offset-4">{showFind?"Close owner search":"Don't know your TDN? Find by owner name"}<ArrowRight aria-hidden="true" className="h-4 w-4"/></button>
        <section id="owner-finder" hidden={!showFind} className="mt-2 rounded-2xl bg-white p-4 text-slate-900">
          <h2 className="font-bold">Find a property by owner name</h2>
          <form onSubmit={handleFind} action="/help" className="mt-3 space-y-3" aria-busy={findLoading}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div><label htmlFor="owner-name" className="block text-sm font-semibold">Owner name</label><input id="owner-name" type="text" maxLength={60} value={findName} disabled={findLoading} onChange={e=>{setFindName(e.target.value);setFindError("");}} aria-invalid={!!findError} aria-describedby={findError?"owner-search-help owner-search-error":"owner-search-help"} className="mt-1 w-full rounded-lg border border-slate-400 px-3 py-3 text-base"/></div>
              <div><label htmlFor="owner-barangay" className="block text-sm font-semibold">Barangay <span className="font-normal">(optional)</span></label><input id="owner-barangay" type="text" maxLength={60} value={barangay} disabled={findLoading} onChange={e=>setBarangay(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-400 px-3 py-3 text-base"/></div>
            </div>
            <p id="owner-search-help" className="text-xs text-slate-600">Use at least three characters. Add the barangay to narrow the results.</p>
            <button disabled={findLoading} className="min-h-11 rounded-lg bg-blue-800 px-5 py-3 text-sm font-bold text-white hover:bg-blue-900 disabled:opacity-60">{findLoading?"Finding…":"Find properties"}</button>
            {findError&&<p id="owner-search-error" role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">{findError}</p>}
            {findMessage&&<p role="status" className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900">{findMessage}</p>}
          </form>
          {findResults.length>0&&<div className="mt-4 space-y-2" aria-label="Owner search results">{findResults.map((result,index)=><Link key={result.account_key||index}
            href={"/property/"+encodeURIComponent(result.td_number)+(result.account_key?"?account="+encodeURIComponent(result.account_key):"")} className="block rounded-lg border border-slate-300 p-3 hover:bg-blue-50"><span className="block font-bold">{result.owner_name}</span><span className="text-sm text-slate-600">{result.td_number} · {result.barangay||"Location unavailable"} · {result.kind||"Property"}</span></Link>)}</div>}
        </section>
        <ul className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-blue-100" aria-label="Portal scope">
          <li className="flex items-center gap-1.5"><Shield aria-hidden="true" className="h-4 w-4"/>Read-only inquiry</li>
          <li className="flex items-center gap-1.5"><CalendarDays aria-hidden="true" className="h-4 w-4"/>Records from 2023</li>
          <li className="flex items-center gap-1.5"><Landmark aria-hidden="true" className="h-4 w-4"/>Published office records</li>
        </ul>
      </div>
    </section>
    <section className="mx-auto max-w-5xl px-4 py-8 sm:py-10" aria-labelledby="portal-help-title">
      <h2 id="portal-help-title" className="text-xl font-bold">Before you visit the office</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">{[
        {title:"Find your record",text:"Use your TDN or PIN to view a published property account. Separate accounts with a shared TDN are not combined.",icon:Search},
        {title:"Review the publication date",text:"This is a published snapshot, not a live connection to the office database. Check when records were last updated.",icon:CalendarDays},
        {title:"Pay or request a correction",text:"Bring your TDN and valid ID to the Treasury Office. Online inquiry does not replace an official receipt or tax clearance.",icon:FileText},
      ].map(({title,text,icon:Icon})=><article key={title} className="rounded-xl border border-slate-200 bg-white p-5"><Icon aria-hidden="true" className="mb-3 h-6 w-6 text-blue-800"/><h3 className="font-bold">{title}</h3><p className="mt-2 text-sm leading-6 text-slate-600">{text}</p></article>)}</div>
      <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 p-5"><h3 className="font-bold text-amber-950">Payment information</h3><p className="mt-2 text-sm leading-6 text-amber-950">{PAYMENT_GUIDANCE}</p><Link href="/pay-guide" className="mt-3 inline-flex min-h-11 items-center gap-2 font-semibold text-blue-800 underline underline-offset-4">How to pay at the office<ArrowRight aria-hidden="true" className="h-4 w-4"/></Link></div>
    </section>
  </div>;
}
