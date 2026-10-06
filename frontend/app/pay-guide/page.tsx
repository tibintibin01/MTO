import { MapPin, Clock, Phone, Banknote, Calendar, Percent, AlertCircle, FileText, CheckCircle2 } from "lucide-react";
import Link from "next/link";
import {PAYMENT_GUIDANCE} from "../../lib/publicGuidance";

export const metadata = {
  title: "How to Pay | Dipaculao Treasury Portal",
  description: "Step-by-step guide to paying your Real Property Tax at the Municipal Treasury Office of Dipaculao, Aurora — deadlines, discounts, and penalties.",
};

const steps = [
  {
    n: "1",
    title: "Know your balance",
    desc: "Search using your TDN or PIN and check the displayed publication time. The published balance is for inquiry; the office confirms the current computation. If available, bring your inquiry Statement of Account (SOA).",
    icon: FileText,
  },
  {
    n: "2",
    title: "Visit the Treasury Office",
    desc: "Go to the Municipal Treasury Office at Doña Aurora St., North Poblacion, Dipaculao, Aurora. Bring your TDN (or printed SOA) and a valid government-issued ID.",
    icon: MapPin,
  },
  {
    n: "3",
    title: "Pay at the cashier",
    desc: "Present your TDN to the cashier. They will compute your total — including any prompt-payment discount or penalty — and issue an Official Receipt (OR).",
    icon: Banknote,
  },
  {
    n: "4",
    title: "Keep your receipt",
    desc: "Your Official Receipt is proof of payment. Portal records change only after the office publishes a new snapshot. Check its publication time; if a payment is missing, contact the Treasury Office rather than assuming it was not recorded.",
    icon: CheckCircle2,
  },
];

export default function PayGuide() {
  return (
    <div className="bg-[#eef2f7] min-h-screen">
      {/* Hero */}
      <section className="bg-gradient-to-br from-[#1a3a6b] via-[#1f4e78] to-[#0f2a5e] text-white py-12 px-4">
        <div className="max-w-4xl mx-auto">
          <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-blue-200 hover:text-white mb-5">
            ← Back to Search
          </Link>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight mb-2">How to Pay Your Property Tax</h1>
          <p className="text-blue-200 text-base max-w-2xl">
            Payments are made in person at the Municipal Treasury Office. Follow these steps for a quick, hassle-free transaction.
          </p>
        </div>
      </section>

      {/* Steps */}
      <section className="max-w-4xl mx-auto px-4 py-10">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
          {steps.map(({ n, title, desc, icon: Icon }) => (
            <div key={n} className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-[#1a3a6b] text-white font-black flex items-center justify-center flex-shrink-0">
                  {n}
                </div>
                <Icon className="w-5 h-5 text-[#367588]" />
                <h2 className="font-bold text-slate-800">{title}</h2>
              </div>
              <p className="text-sm text-slate-500 leading-relaxed">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Discounts & penalties */}
      <section className="max-w-4xl mx-auto px-4 pb-10">
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2">
            <Percent className="w-4 h-4 text-[#367588]" />
            <h2 className="font-bold text-slate-800">Discounts &amp; Penalties</h2>
          </div>
          <p className="px-6 py-5 text-sm leading-6 text-slate-700">{PAYMENT_GUIDANCE}</p>
        </div>
      </section>

      {/* Office info */}
      <section className="max-w-4xl mx-auto px-4 pb-12">
        <div className="rounded-2xl p-6 text-white" style={{ background: "#1a3a8f" }}>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div className="flex items-start gap-3">
              <MapPin className="w-5 h-5 text-yellow-300 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs uppercase tracking-wider" style={{ color: "#a8b8e8" }}>Location</p>
                <p className="text-sm font-semibold">Doña Aurora St., North Poblacion, Dipaculao, Aurora 3203</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Clock className="w-5 h-5 text-yellow-300 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs uppercase tracking-wider" style={{ color: "#a8b8e8" }}>Office Hours</p>
                <p className="text-sm font-semibold">Mon–Fri, 8:00 AM – 5:00 PM</p>
                <p className="text-xs" style={{ color: "#a8b8e8" }}>Excluding holidays</p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Phone className="w-5 h-5 text-yellow-300 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs uppercase tracking-wider" style={{ color: "#a8b8e8" }}>Need Help?</p>
                <Link href="/help" className="text-sm font-semibold underline hover:text-yellow-300">
                  Visit Help &amp; Support
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
