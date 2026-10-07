import { MapPin, Clock, Phone, HelpCircle, FileText, AlertCircle, CheckCircle, Search } from "lucide-react";
import {PAYMENT_GUIDANCE} from "../../lib/publicGuidance";

export const metadata = {
  title: "Help & Support | Dipaculao Treasury Portal",
  description: "Frequently asked questions and contact information for the Municipal Treasury Office of Dipaculao, Aurora.",
};

const faqs = [
  {
    q: "What is a Tax Declaration Number (TDN)?",
    a: "A Tax Declaration Number (TDN) identifies a property declaration. Some authorized separate accounts can share a TDN; select the correct property if multiple matches appear. A common format is 06-XXXX-XXXXX (e.g. 06-0012-01379). Find it on your receipt, tax declaration or assessment notice.",
  },
  {
    q: "Where can I find my TDN if I lost my receipt?",
    a: "Visit the Municipal Treasury Office or the Municipal Assessor's Office at Doña Aurora St., North Pob., Dipaculao, Aurora. Bring a valid government-issued ID and proof of ownership (title, deed of sale, or tax declaration). Staff will assist you in locating your property record.",
  },
  {
    q: "What does 'Delinquent' status mean?",
    a: "The published record shows an unpaid balance on one or more tax years. Check the publication date and confirm the current amount and applicable penalties with the Municipal Treasury Office.",
  },
  {
    q: "What does 'Compliant' status mean?",
    a: "The published record shows no outstanding balance across the billed tax years. Excess payments remain attached to their tax year and do not automatically settle another year's balance. This inquiry result does not replace an official tax clearance.",
  },
  {
    q: "What are the payment deadlines and discounts?",
    a: PAYMENT_GUIDANCE,
  },
  {
    q: "Can I pay my real property tax online?",
    a: "At this time, payments must be made in person at the Municipal Treasury Office. This portal is for inquiry purposes only — to view your property record, payment history, and outstanding balance. For payment, please visit the office during business hours.",
  },
  {
    q: "My property information is incorrect. How do I correct it?",
    a: "Visit the Municipal Assessor's Office with supporting documents (title, deed of sale, or other proof of ownership). Corrections to assessed value, owner name, or property classification are processed there. Once corrected, the Treasury records will be updated accordingly.",
  },
  {
    q: "The portal shows data starting from 2023. What about older payments?",
    a: "This system currently contains payment and billing records from 2023 onwards. Records prior to 2023 are maintained in physical ledgers at the Municipal Treasury Office. For historical payment verification, please visit the office in person.",
  },
  {
    q: "I searched my TDN but it says 'No property found'. What should I do?",
    a: "Check your TDN or PIN against the document. For example, TDN 06-0012-01379 can also be entered as 06001201379. Use the exact PIN printed on your document. If records are awaiting an update or a search error appears, that does not mean your property is absent; contact the office for assistance.",
  },
  {q:"How current is the portal?",a:"This portal uses a read-only snapshot published by the office. The publication time is shown in Philippine time. Records beyond the freshness limit are withheld until the office publishes an update. Your receipt remains proof of payment; contact the Treasury Office for current figures or corrections."},
];

export default function HelpPage() {
  return (
    <div className="flex flex-col">

      {/* ── Hero ── */}
      <section className="bg-gradient-to-br from-[#1a3a6b] via-[#1f4e78] to-[#0f2a5e] text-white py-14 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <div className="w-14 h-14 bg-white/10 rounded-2xl flex items-center justify-center mx-auto mb-5">
            <HelpCircle className="w-7 h-7 text-yellow-300" />
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight mb-3">
            Help &amp; Support
          </h2>
          <p className="text-blue-200 text-base max-w-xl mx-auto">
            Answers to common questions about the Real Property Tax portal of
            the Municipal Treasury Office of Dipaculao, Aurora.
          </p>
        </div>
      </section>

      {/* ── Contact card ── */}
      <section className="max-w-5xl mx-auto px-4 py-10 w-full">
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="bg-[#1a3a6b] px-6 py-4">
            <h3 className="text-white font-bold text-base">Municipal Treasury Office</h3>
            <p className="text-blue-200 text-sm">Bayan ng Dipaculao, Aurora</p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-slate-100">
            <div className="flex items-start gap-4 p-6">
              <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center flex-shrink-0">
                <MapPin className="w-5 h-5 text-[#1a3a6b]" />
              </div>
              <div>
                <p className="font-bold text-slate-800 text-sm mb-1">Address</p>
                <p className="text-slate-500 text-sm leading-relaxed">
                  Doña Aurora St., North Pob.<br />
                  Dipaculao, Aurora 3203
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4 p-6">
              <div className="w-10 h-10 bg-yellow-50 rounded-xl flex items-center justify-center flex-shrink-0">
                <Clock className="w-5 h-5 text-yellow-600" />
              </div>
              <div>
                <p className="font-bold text-slate-800 text-sm mb-1">Office Hours</p>
                <p className="text-slate-500 text-sm leading-relaxed">
                  Monday – Friday<br />
                  8:00 AM – 5:00 PM<br />
                  <span className="text-xs text-slate-400">Excluding public holidays</span>
                </p>
              </div>
            </div>
            <div className="flex items-start gap-4 p-6">
              <div className="w-10 h-10 bg-green-50 rounded-xl flex items-center justify-center flex-shrink-0">
                <FileText className="w-5 h-5 text-green-600" />
              </div>
              <div>
                <p className="font-bold text-slate-800 text-sm mb-1">What to Bring</p>
                <p className="text-slate-500 text-sm leading-relaxed">
                  Valid government ID<br />
                  Tax Declaration / Receipt<br />
                  Proof of ownership
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Quick tips ── */}
      <section className="max-w-5xl mx-auto px-4 pb-8 w-full">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="bg-blue-50 border border-blue-100 rounded-2xl p-5 flex gap-3">
            <Search className="w-5 h-5 text-[#1a3a6b] flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-slate-800 text-sm">How to Search</p>
              <p className="text-slate-500 text-xs mt-1 leading-relaxed">
                Enter your TDN in the format <strong>06-XXXX-XXXXX</strong> on the home page and click Search Property.
              </p>
            </div>
          </div>
          <div className="bg-yellow-50 border border-yellow-100 rounded-2xl p-5 flex gap-3">
            <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-slate-800 text-sm">Penalty Reminder</p>
              <p className="text-slate-500 text-xs mt-1 leading-relaxed">
                {PAYMENT_GUIDANCE}
              </p>
            </div>
          </div>
          <div className="bg-green-50 border border-green-100 rounded-2xl p-5 flex gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-slate-800 text-sm">Data Coverage</p>
              <p className="text-slate-500 text-xs mt-1 leading-relaxed">
                This portal shows records from <strong>2023 onwards</strong>. For older records, visit the office.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="max-w-5xl mx-auto px-4 pb-14 w-full">
        <h3 className="font-extrabold text-slate-800 text-xl mb-6">
          Frequently Asked Questions
        </h3>
        <div className="space-y-4">
          {faqs.map((faq, i) => (
            <div
              key={i}
              className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6"
            >
              <p className="font-bold text-slate-800 text-sm mb-2 flex items-start gap-2">
                <span className="w-5 h-5 bg-[#1a3a6b] text-white rounded-full flex items-center justify-center text-xs flex-shrink-0 mt-0.5">
                  {i + 1}
                </span>
                {faq.q}
              </p>
              <p className="text-slate-500 text-sm leading-relaxed pl-7">
                {faq.a}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Bottom CTA ── */}
      <section className="bg-[#1a3a6b] text-white py-10 px-4">
        <div className="max-w-5xl mx-auto text-center">
          <p className="font-bold text-lg mb-2">Still have questions?</p>
          <p className="text-blue-200 text-sm mb-6">
            Visit us at the Municipal Treasury Office during business hours and our staff will be happy to assist you.
          </p>
          <a
            href="/"
            className="inline-flex items-center gap-2 bg-yellow-400 text-[#0f2a5e] px-6 py-3 rounded-xl font-bold text-sm hover:bg-yellow-300 transition-colors"
          >
            <Search className="w-4 h-4" />
            Back to Property Search
          </a>
        </div>
      </section>

    </div>
  );
}
