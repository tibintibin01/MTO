import Link from "next/link";
import {ArrowLeft,ArrowRight,FileText,CheckCircle2,AlertCircle,MapPin,
  CalendarDays,ChevronDown,Copy,Check,Home,Clock3,Shield,Building2} from "lucide-react";
import {formatPublishedAt} from "../../lib/portalFreshness";
import {PAYMENT_GUIDANCE} from "../../lib/publicGuidance";

type Props={
  data:any;id:string;accountQuery:string;balance:number;totalCredit:number;
  breakdown:any[];sorted:any[];totalPaid:number;historyCount:number;
  isDelinquent:boolean;isPending:boolean;isCompliant:boolean;
  historyState:"loading"|"ready"|"error";historyError:string;
  retrying:boolean;copied:boolean;billingOpen:boolean;
  onCopy:()=>void;onRetry:()=>void;onBillingToggle:()=>void;peso:(value:number)=>string;
};

/** Presentation only. Amounts and account identity come from the guarded loader. */
export function PropertyWorkspace(p:Props){
  const {data,id,accountQuery,balance,totalCredit,breakdown,sorted,totalPaid,
    historyCount,isDelinquent,isPending,isCompliant,historyState,historyError,
    retrying,copied,billingOpen,onCopy,onRetry,onBillingToggle,peso}=p;
  return <div className="property-page">
    <section className="property-hero" aria-labelledby="property-record-title">
      <div className="property-frame">
        <div className="property-breadcrumb"><Link href="/"><ArrowLeft size={15} aria-hidden="true"/>Back to Search</Link><span>PROPERTY WORKSPACE</span></div>
        <div className="property-identity-grid">
          <div className="property-identity">
            <div className="property-record-heading"><p className="property-eyebrow">YOUR PROPERTY RECORD</p>
              <span className={"property-status "+(isDelinquent?"requires-payment":isCompliant?"updated":"pending")}>
                {isDelinquent?<AlertCircle size={13} aria-hidden="true"/>:isCompliant?<CheckCircle2 size={13} aria-hidden="true"/>:<Clock3 size={13} aria-hidden="true"/>}
                {isDelinquent?"Payment Required":isCompliant?"Account Updated":"Not Yet Billed"}
              </span>
            </div>
            <h1 id="property-record-title">{data.td_number}</h1>
            <div className="property-identifiers">
              {data.pin&&<span>PIN: {data.pin}</span>}
              <button onClick={onCopy} type="button">{copied?<Check size={14} aria-hidden="true"/>:<Copy size={14} aria-hidden="true"/>}{copied?"Copied!":"Copy TDN"}</button>
            </div>
            <dl className="property-owner-details">
              <div><dt><Building2 size={14} aria-hidden="true"/>Owner</dt><dd>{data.owner_name}</dd></div>
              <div><dt><MapPin size={14} aria-hidden="true"/>Location</dt><dd>{data.location}</dd></div>
            </dl>
          </div>
          <section className="property-assessment" aria-label="Published assessment">
            <span className="property-assessment-icon"><Home size={23} aria-hidden="true"/></span>
            <p className="property-eyebrow">ASSESSED VALUE</p><p className="property-assessment-value">{peso(data.assessed_value)}</p>
            {data.assessment_as_of_year&&<p className="property-assessment-caption">Effective assessment as of {data.assessment_as_of_year}</p>}
            {data.kind&&<span className="property-kind">{data.kind}</span>}
            {data.future_assessment&&<div className="property-future-assessment"><span>Future assessment</span>
              <strong>{peso(Number(data.future_assessment.assessed_value||0))} <small>effective {data.future_assessment.effective_year}</small></strong>
            </div>}
          </section>
        </div>
        <div className="property-publication"><Clock3 size={14} aria-hidden="true"/><p>Records published: <strong>{formatPublishedAt(data.published_at)}</strong></p></div>
      </div>
    </section>

    <div className="property-frame property-content">
      <section className={"property-balance-card "+(isDelinquent?"has-balance":isPending?"not-billed":"settled")} aria-labelledby="property-balance-title">
        <div className="property-balance-main">
          <span className="property-balance-icon">{isDelinquent?<AlertCircle size={25} aria-hidden="true"/>:isPending?<Clock3 size={25} aria-hidden="true"/>:<CheckCircle2 size={25} aria-hidden="true"/>}</span>
          <div><h2 id="property-balance-title">{isDelinquent?"Outstanding balance":isPending?"Not Yet Billed":"Fully Paid"}</h2>
            <p className="property-balance-value">{isPending?"—":peso(balance)}</p>
            <p className="property-balance-caption">{isDelinquent?`Outstanding across ${breakdown.length} tax year(s) · as of ${data.as_of??""}`:isPending?"No billing records for this property yet":"No outstanding balance — your account is updated"}</p>
          </div>
        </div>
        <div className="property-actions"><Link href="/pay-guide" className="property-button primary">How to Pay<ArrowRight size={16} aria-hidden="true"/></Link>
          <a href={`/api/public/property/${encodeURIComponent(id)}/soa${accountQuery}`} target="_blank" rel="noopener noreferrer" className="property-button secondary"><FileText size={16} aria-hidden="true"/>Download SOA</a>
        </div>
      </section>
      {totalCredit>0&&<div className="property-credit-note"><AlertCircle size={17} aria-hidden="true"/><p><strong>Unapplied credit: {peso(totalCredit)}</strong> · retained by tax year pending verification. It has not been transferred to another year&apos;s balance.</p></div>}

      <section className="property-stat-grid" aria-label="Account summary">
        <article className="property-stat"><span className="property-stat-icon"><CheckCircle2 size={21} aria-hidden="true"/></span><div><h2>Total Paid</h2>
          <p className="property-stat-value">{typeof data.total_paid==="number"?peso(data.total_paid):historyState==="ready"?peso(totalPaid):"Unavailable"}</p>
          <p>{historyState==="ready"?`${historyCount} payment(s) on record`:historyState==="error"?"Payment history unavailable":"Loading payment history…"}</p>
        </div></article>
        <article className="property-stat"><span className="property-stat-icon gold"><FileText size={21} aria-hidden="true"/></span><div><h2>Total Billed</h2><p className="property-stat-value">{peso(data.total_due??0)}</p><p>{breakdown.length} tax year(s)</p></div></article>
        <article className="property-stat"><span className="property-stat-icon blue"><CalendarDays size={21} aria-hidden="true"/></span><div><h2>Last Payment</h2><p className="property-stat-value">{data.last_payment?.date_paid??sorted[0]?.date_paid??"—"}</p><p>{data.last_payment?.period??sorted[0]?.period?`Tax year ${data.last_payment?.period??sorted[0]?.period}`:historyState==="ready"?"No payments recorded":"History details unavailable"}</p></div></article>
      </section>

      {breakdown.length>0&&<section className="property-panel property-billing" aria-labelledby="billing-title">
        <button type="button" onClick={onBillingToggle} aria-expanded={billingOpen} aria-controls="property-billing-content" className="property-panel-toggle">
          <span className="property-panel-icon"><FileText size={19} aria-hidden="true"/></span><span className="property-panel-label"><span id="billing-title">Billing Breakdown</span><small>{breakdown.length} tax year(s) · Basic + SEF + Penalty − Discount applied</small></span>
          <span className={"property-billing-total "+(balance>0?"due":"paid")}>{balance>0?`${peso(balance)} due`:"Fully paid"}</span><ChevronDown size={19} aria-hidden="true" className={billingOpen?"is-open":""}/>
        </button>
        <div id="property-billing-content" hidden={!billingOpen}>
          <div className="property-table-scroll property-billing-desktop">
            <table className="property-table"><caption className="sr-only">Yearly billing amounts from the published property record</caption><thead><tr>{["Year","Assessed","Basic","SEF","Penalty","Discount applied","Due","Paid","Credit","Balance"].map((heading,index)=><th key={heading} scope="col" className={index===0?"":"numeric"}>{heading}</th>)}</tr></thead>
              <tbody>{breakdown.map((row:any)=><tr key={row.tax_year}>
                <th scope="row">{row.tax_year}</th><td className="numeric">{peso(row.assessed_value)}</td><td className="numeric">{peso(row.basic)}</td><td className="numeric">{peso(row.sef)}</td><td className="numeric">{peso(row.penalty)}</td><td className="numeric">{peso(row.discount)}</td>
                <td className="numeric strong">{peso(row.total_due)}</td><td className="numeric">{peso(row.amount_paid)}</td><td className={"numeric "+(row.credit>0?"credit":"")}>{peso(row.credit)}</td><td className={"numeric strong "+(row.balance>0?"due":"paid")}>{peso(row.balance)}</td>
              </tr>)}</tbody></table>
          </div>
          <div className="property-billing-mobile">{breakdown.map((row:any)=><article key={row.tax_year} className="property-year-card">
            <div className="property-year-top"><h3>Tax year {row.tax_year}</h3><strong className={row.balance>0?"due":"paid"}>{row.balance>0?peso(row.balance):"Paid"}</strong></div>
            <dl>{[["Assessed",row.assessed_value],["Basic",row.basic],["SEF",row.sef],["Penalty",row.penalty],["Discount applied",row.discount],["Due",row.total_due],["Paid",row.amount_paid],["Credit",row.credit]].map(([label,value])=><div key={label as string}><dt>{label}</dt><dd className={label==="Credit"&&row.credit>0?"credit":""}>{peso(value as number)}</dd></div>)}</dl>
          </article>)}</div>
          <p className="property-table-note">These are published figures. Discounts shown are amounts already applied; confirm the official computation with the Treasury Office when paying.</p>
        </div>
      </section>}

      <div className="property-detail-grid">
        <section className="property-panel property-history" aria-labelledby="history-title">
          <div className="property-panel-header"><span className="property-panel-icon"><FileText size={19} aria-hidden="true"/></span><h2 id="history-title">Payment History</h2><span className="property-history-range">From 2023 onwards</span></div>
          <p className="property-history-note">Records shown are from <strong>January 2023</strong> onwards. For earlier transactions, visit the Municipal Treasury Office with your TDN and a valid ID.</p>
          {historyState==="loading"?<p role="status" className="property-history-state">Loading payment history…</p>:historyState==="error"?<div className="property-history-state">
            <p role="alert" className="property-inline-error">{historyError}</p><button onClick={onRetry} disabled={retrying} className="property-button primary">Retry payment history</button><p className="property-history-explanation">An unavailable history does not mean there are no payments.</p>
          </div>:sorted.length>0?<>
            <div className="property-table-scroll property-history-desktop"><table className="property-table"><caption className="sr-only">Published official receipt and payment history</caption><thead><tr>{["Period","OR Number","Date Paid","Amount","Status"].map(heading=><th key={heading} scope="col" className={heading==="Amount"||heading==="Status"?"numeric":""}>{heading}</th>)}</tr></thead>
              <tbody>{sorted.map((row,index)=><tr key={index}><th scope="row">{row.period}</th><td className="receipt-number">{row.or_number}</td><td>{row.date_paid}</td><td className="numeric strong">{peso(row.amount)}</td><td className="numeric"><span className="property-payment-status"><CheckCircle2 size={12} aria-hidden="true"/>Paid</span></td></tr>)}</tbody>
              <tfoot><tr><th colSpan={3} scope="row">Total Recorded</th><td className="numeric strong paid">{peso(totalPaid)}</td><td/></tr></tfoot>
            </table></div>
            <div className="property-history-mobile">{sorted.map((row,index)=><article key={index} className="property-receipt-card">
              <div className="property-receipt-top"><strong>{row.period}</strong><span className="property-payment-status"><CheckCircle2 size={12} aria-hidden="true"/>Paid</span></div>
              <dl><div><dt>OR Number</dt><dd className="receipt-number">{row.or_number}</dd></div><div><dt>Date Paid</dt><dd>{row.date_paid}</dd></div></dl>
              <div className="property-receipt-amount"><span>Amount Paid</span><strong>{peso(row.amount)}</strong></div>
            </article>)}<div className="property-history-total"><span>Total Recorded</span><strong>{peso(totalPaid)}</strong></div></div>
          </>:<div className="property-empty-history"><span className="property-empty-icon"><FileText size={26} aria-hidden="true"/></span><p>No payment records found</p><small>Records available from January 2023 onwards</small></div>}
        </section>
        <aside className="property-next-steps" aria-labelledby="property-next-title"><span className="property-help-icon"><MapPin size={23} aria-hidden="true"/></span><p className="property-eyebrow">YOUR NEXT STEP</p><h2 id="property-next-title">Need to pay or <br/>update your record?</h2><p>Bring your TDN and a valid ID to the Municipal Treasury Office.</p><Link href="/pay-guide">Plan your office visit<ArrowRight size={16} aria-hidden="true"/></Link><Link href="/help">Help &amp; Support<ArrowRight size={16} aria-hidden="true"/></Link>
          <details className="property-guidance"><summary><Shield size={14} aria-hidden="true"/>About these figures</summary><p>{PAYMENT_GUIDANCE}</p><p>An online inquiry does not replace an official receipt or tax clearance.</p></details>
        </aside>
      </div>
    </div>
  </div>;
}
