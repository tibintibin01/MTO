"use client";

import {useEffect,useRef,useState} from "react";
import {useRouter} from "next/navigation";
import Link from "next/link";
import {AlertCircle,ArrowRight,CalendarDays,FileText,Landmark,Search,Shield,MapPin,MoveUpRight} from "lucide-react";
import {unavailableMessage} from "../../lib/portalFreshness";
import {PAYMENT_GUIDANCE} from "../../lib/publicGuidance";

const QUERY_PATTERN=/^[A-Za-z0-9][A-Za-z0-9\-./# ]{1,49}$/;
type Match={account_key:string;owner_name:string;pin:string|null;barangay:string|null;location:string|null;kind:string|null};
async function readResponse(url:string){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),15_000);
  try{const response=await fetch(url,{cache:"no-store",signal:controller.signal});return{response,payload:await response.json()};}
  finally{clearTimeout(timeout);}
}
// Artwork is supplied by the server page, not imported into the client bundle.
export function LandingHome({artwork}:{artwork:React.ReactNode}){
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
  return <div className="portal-landing">
    <section className="landing-hero" aria-labelledby="landing-title">
      <div className="landing-hero-lines" aria-hidden="true"/>
      <div className="landing-hero-inner">
      <div className="landing-hero-content">
        <p className="landing-eyebrow"><span/> DIPACULAO · PUBLIC TREASURY PORTAL</p>
        <h1 id="landing-title">Property tax,<br/><span>made clear.</span></h1>
        <p className="landing-intro">Your assessment, payment history and published balance.<br className="hidden sm:block"/> A clearer picture before your next visit.</p>
        <noscript><p className="mt-4 rounded-lg bg-amber-100 p-3 text-sm text-amber-950">JavaScript is required for property lookup. Enable it or <a href="/help" className="underline">contact the Treasury Office for assistance.</a></p></noscript>
        <form onSubmit={handleSearch} action="/help" className="landing-search-card" aria-busy={loading}>
          <label htmlFor="property-query" className="block text-sm font-bold">Tax Declaration Number or PIN</label>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <input id="property-query" type="text" value={query} disabled={!interactive||loading} maxLength={50}
              onChange={e=>{setQuery(e.target.value);setError("");setMatches([]);}}
              aria-invalid={!!error} aria-describedby={error?"property-query-help property-query-error":"property-query-help"}
              autoComplete="off" spellCheck={false} placeholder="e.g. 06-0012-01379"
              className="landing-search-input min-w-0 flex-1 rounded-lg border border-slate-400 px-3 py-3 text-base placeholder:text-slate-600 disabled:bg-slate-100"/>
            <button type="submit" disabled={!interactive||loading} className="landing-search-button flex min-h-12 items-center justify-center gap-2 rounded-lg px-5 py-3 text-sm font-bold text-white disabled:opacity-60"><Search aria-hidden="true" className="h-4 w-4"/>{loading?"Searching…":"Search property"}</button>
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
          className="landing-owner-toggle inline-flex min-h-11 items-center gap-2 rounded-lg text-sm font-semibold underline underline-offset-4">{showFind?"Close owner search":"Don't know your TDN? Find by owner name"}<ArrowRight aria-hidden="true" className="h-4 w-4 shrink-0"/></button>
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
        <ul className="landing-scope" aria-label="Portal scope">
          <li className="flex items-center gap-1.5"><Shield aria-hidden="true" className="h-4 w-4"/>Read-only inquiry</li>
          <li className="flex items-center gap-1.5"><CalendarDays aria-hidden="true" className="h-4 w-4"/>Records from 2023</li>
          <li className="flex items-center gap-1.5"><Landmark aria-hidden="true" className="h-4 w-4"/>Published office records</li>
        </ul>
      </div>
      {artwork}
      </div>
      <div className="landing-hero-bottom" aria-hidden="true"><span>YOUR COMMUNITY. YOUR RECORDS.</span><span>DIPACULAO / AURORA</span></div>
    </section>
    <section className="landing-services" aria-labelledby="portal-help-title">
      <div className="landing-section-heading">
        <div><p className="landing-section-kicker">A USEFUL STOP. EVERY TIME.</p><h2 id="portal-help-title">Less guesswork.<br/>More clarity.</h2></div>
        <p>Check your published records, prepare for your visit, and find the right next step—all in one place.</p>
      </div>
      <div className="landing-service-grid">{[
        {title:"Find your property",text:"See your assessment, payments and published balance. Accounts that share a TDN stay separate.",icon:Search,href:"#property-query",label:"Look up a record",tone:"sea"},
        {title:"Plan your office visit",text:"Know what to bring and where to pay. Your online inquiry helps you prepare for your next visit.",icon:Landmark,href:"/pay-guide",label:"View the payment guide",tone:"gold"},
        {title:"A little help goes a long way",text:"Can't find your record or need a correction? Get guidance from the Municipal Treasury Office.",icon:MapPin,href:"/help",label:"Find help & guidance",tone:"blue"},
      ].map(({title,text,icon:Icon,href,label,tone},index)=><article key={title} className={"landing-service-card landing-service-"+tone}>
        <div className="landing-service-top"><span className="landing-service-icon"><Icon aria-hidden="true" size={23}/></span><span className="landing-service-number">0{index+1}</span></div>
        <h3>{title}</h3><p>{text}</p>
        <Link href={href} className="landing-service-link">{label}<MoveUpRight aria-hidden="true" size={17}/></Link>
      </article>)}</div>
      <div className="landing-record-note"><CalendarDays aria-hidden="true" size={20}/><p><strong>A published snapshot, not a live account.</strong> Check the publication date above. Figures can change after the last update.</p></div>
      <div className="landing-payment-note"><span className="landing-payment-icon"><FileText aria-hidden="true" size={24}/></span><div><h3>Ready for your next step?</h3><p>{PAYMENT_GUIDANCE}</p></div><Link href="/pay-guide">How to pay at the office<ArrowRight aria-hidden="true" size={18}/></Link></div>
    </section>
  </div>;
}
