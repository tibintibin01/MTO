"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  AlertCircle,
  ArrowRight,
  BadgeCheck,
  CalendarDays,
  Clock,
  FileText,
  Landmark,
  MapPin,
  Phone,
  Search,
  Shield,
} from "lucide-react";

const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{1,49}$/;

const heroCards = [
  {
    label: "Read-only",
    detail: "Public inquiry access",
    icon: Shield,
    tone: "from-blue-500/35 to-cyan-300/10",
  },
  {
    label: "From 2023",
    detail: "Payment history",
    icon: CalendarDays,
    tone: "from-sky-500/35 to-blue-200/10",
  },
  {
    label: "Official",
    detail: "Municipal snapshot",
    icon: BadgeCheck,
    tone: "from-amber-300/35 to-yellow-100/10",
  },
];

const informationCards = [
  {
    title: "Secure Access",
    desc: "Data is transmitted over an encrypted connection. Your privacy and property information are protected under RA 10173.",
    icon: Shield,
    color: "text-blue-700",
    bg: "bg-blue-50",
  },
  {
    title: "Payment History",
    desc: "View your official OR numbers, tax years covered, amounts paid, and outstanding balances. Data available from 2023.",
    icon: FileText,
    color: "text-amber-700",
    bg: "bg-amber-50",
  },
  {
    title: "Assessment Data",
    desc: "Check your property's assessed value, classification, lot number, and barangay location in real time.",
    icon: MapPin,
    color: "text-emerald-700",
    bg: "bg-emerald-50",
  },
];

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // "Find my TDN" by owner name + barangay
  const [showFind, setShowFind] = useState(false);
  const [findName, setFindName] = useState("");
  const [findBarangay, setFindBarangay] = useState("");
  const [findResults, setFindResults] = useState<any[]>([]);
  const [findError, setFindError] = useState("");
  const [findLoading, setFindLoading] = useState(false);
  const [findMessage, setFindMessage] = useState("");

  const handleFind = async (e: React.FormEvent) => {
    e.preventDefault();
    setFindError("");
    setFindMessage("");
    setFindResults([]);
    if (findName.trim().length < 3) {
      setFindError("Please enter at least 3 characters of the owner's name.");
      return;
    }
    setFindLoading(true);
    try {
      const params = new URLSearchParams({ name: findName.trim() });
      if (findBarangay.trim()) params.set("barangay", findBarangay.trim());
      const res = await fetch(`/api/public/find?${params}`, { cache: "no-store" });
      if (res.status === 400) {
        const j = await res.json();
        setFindError(j.detail || "Invalid search.");
        return;
      }
      if (!res.ok) {
        setFindError("Unable to search right now. Please try again.");
        return;
      }
      const data = await res.json();
      if (data.too_many) {
        setFindMessage(data.message || "Too many matches. Add your barangay or more of your name.");
        return;
      }
      if (!data.results || data.results.length === 0) {
        setFindMessage("No matching properties found. Check the spelling or visit the office.");
        return;
      }
      setFindResults(data.results);
    } catch {
      setFindError("Network error. Please try again.");
    } finally {
      setFindLoading(false);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Please enter a Tax Declaration Number or PIN.");
      return;
    }
    if (!QUERY_PATTERN.test(trimmed)) {
      setError("Invalid format. Use your TDN (e.g. 06-0012-01379) or PIN.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`/api/public/property/${encodeURIComponent(trimmed)}`, { cache: "no-store" });
      if (res.status === 404) {
        setError("No property found for that TDN or PIN. Please check and try again.");
        return;
      }
      if (!res.ok) {
        setError("Unable to reach the server. Please try again shortly.");
        return;
      }
      router.push(`/property/${encodeURIComponent(trimmed)}`);
    } catch {
      setError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col">

      {/* ── Hero section ── */}
      <motion.section
        className="relative isolate overflow-hidden bg-[#061832] px-4 pb-20 pt-14 text-white sm:pb-24 sm:pt-20"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
      >
        <div
          className="absolute inset-0 bg-cover bg-center opacity-40"
          style={{ backgroundImage: "url('/municipal-hall.png')" }}
          aria-hidden="true"
        />
        <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(3,18,42,0.98)_0%,rgba(7,34,74,0.90)_42%,rgba(6,22,50,0.80)_100%)]" aria-hidden="true" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_26%,rgba(85,156,255,0.22),transparent_30%),linear-gradient(180deg,rgba(6,24,50,0.12),rgba(6,24,50,0.92))]" aria-hidden="true" />
        <motion.div
          className="absolute -left-[16%] top-[48%] h-28 w-[78%] rounded-full border border-cyan-200/35 bg-cyan-300/10 shadow-[0_0_44px_rgba(56,189,248,0.42)] blur-[1px]"
          style={{ transform: "rotate(-14deg)" }}
          animate={{ x: [-24, 18, -24], y: [0, -10, 0] }}
          transition={{ duration: 13, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden="true"
        />
        <motion.div
          className="absolute -right-[12%] top-[55%] h-24 w-[68%] rounded-full border border-amber-200/50 bg-amber-300/10 shadow-[0_0_52px_rgba(250,204,21,0.42)] blur-[1px]"
          style={{ transform: "rotate(-13deg)" }}
          animate={{ x: [18, -18, 18], y: [0, 9, 0] }}
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden="true"
        />
        <motion.div
          className="absolute left-[11%] top-[24%] hidden h-20 w-20 items-center justify-center rounded-3xl border border-white/20 bg-white/12 shadow-2xl shadow-blue-950/40 backdrop-blur-xl lg:flex"
          animate={{ y: [0, -12, 0], rotate: [-5, 4, -5] }}
          transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden="true"
        >
          <MapPin className="h-9 w-9 text-cyan-200" />
        </motion.div>
        <motion.div
          className="absolute right-[11%] top-[28%] hidden h-20 w-20 items-center justify-center rounded-3xl border border-white/20 bg-white/12 shadow-2xl shadow-blue-950/40 backdrop-blur-xl lg:flex"
          animate={{ y: [0, 12, 0], rotate: [5, -3, 5] }}
          transition={{ duration: 7.5, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden="true"
        >
          <Landmark className="h-9 w-9 text-amber-200" />
        </motion.div>
        <div
          className="absolute inset-x-0 bottom-0 h-28 bg-slate-50"
          style={{ clipPath: "polygon(0 78%, 100% 46%, 100% 100%, 0 100%)" }}
          aria-hidden="true"
        />
        <div className="relative z-10 mx-auto max-w-6xl text-center">
          <motion.div
            className="mb-6 inline-flex items-center gap-2 rounded-full border border-yellow-300/70 bg-yellow-300 px-5 py-2 text-xs font-black uppercase tracking-[0.16em] text-[#09213f] shadow-[0_0_32px_rgba(250,204,21,0.32)]"
            initial={{ y: 12, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.08, duration: 0.45 }}
          >
            <Landmark className="h-4 w-4" />
            Official Government Portal
          </motion.div>
          <motion.h1
            className="mx-auto mb-5 max-w-4xl text-5xl font-black leading-[0.94] tracking-tight text-white drop-shadow-[0_14px_24px_rgba(0,0,0,0.36)] sm:text-6xl lg:text-7xl"
            initial={{ y: 18, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.16, duration: 0.55, ease: "easeOut" }}
          >
            Real Property Tax
            <span className="block bg-gradient-to-b from-yellow-200 via-yellow-300 to-amber-500 bg-clip-text text-transparent">
              Inquiry Portal
            </span>
          </motion.h1>
          <motion.p
            className="mx-auto mb-8 max-w-2xl text-base leading-8 text-blue-100 sm:text-lg"
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.24, duration: 0.5 }}
          >
            Enter your Tax Declaration Number (TDN) or PIN to view your property&apos;s
            assessment, payment history, and outstanding balance.
          </motion.p>

          <motion.div
            className="mx-auto mb-8 grid max-w-4xl gap-4 text-left sm:grid-cols-3"
            initial="hidden"
            animate="visible"
            variants={{
              hidden: {},
              visible: { transition: { staggerChildren: 0.08, delayChildren: 0.28 } },
            }}
          >
            {heroCards.map(({ label, detail, icon: Icon, tone }) => (
              <motion.div
                key={label}
                className={`group rounded-2xl border border-white/20 bg-gradient-to-br ${tone} px-5 py-4 shadow-[0_18px_48px_rgba(2,8,23,0.28)] backdrop-blur-xl transition-transform hover:-translate-y-1`}
                variants={{
                  hidden: { y: 18, opacity: 0 },
                  visible: { y: 0, opacity: 1 },
                }}
              >
                <div className="flex items-center gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/20 bg-white/15 shadow-inner shadow-white/10">
                    <Icon className="h-6 w-6 text-white" />
                  </div>
                  <div>
                    <p className="text-lg font-black text-white">{label}</p>
                    <p className="mt-1 text-sm text-blue-100">{detail}</p>
                  </div>
                </div>
              </motion.div>
            ))}
          </motion.div>

          {/* Search box */}
          <motion.form
            onSubmit={handleSearch}
            className="mx-auto max-w-3xl"
            initial={{ y: 20, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            transition={{ delay: 0.42, duration: 0.55, ease: "easeOut" }}
          >
            <div className="rounded-[2rem] border border-cyan-200/45 bg-white/15 p-3 shadow-[0_0_42px_rgba(56,189,248,0.42),0_30px_70px_rgba(2,8,23,0.45)] backdrop-blur-xl">
            <div className="flex flex-col gap-3 rounded-[1.35rem] bg-white p-2 shadow-xl sm:flex-row">
              <div className="relative flex-1">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <FileText className="h-5 w-5 text-slate-400" />
                </div>
                <input
                  type="text"
                  className="block w-full border-none bg-transparent py-4 pl-11 pr-4 text-base text-slate-800 outline-none placeholder:text-slate-400 focus:ring-0"
                  placeholder="e.g. 06-0012-01379"
                  value={query}
                  onChange={(e) => { setQuery(e.target.value); setError(""); }}
                  aria-label="Tax Declaration Number or PIN"
                  autoComplete="off"
                  spellCheck={false}
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="flex items-center justify-center gap-2 whitespace-nowrap rounded-2xl bg-gradient-to-b from-blue-500 to-blue-800 px-8 py-4 text-sm font-black uppercase text-white shadow-[0_14px_30px_rgba(37,99,235,0.36)] transition-all hover:-translate-y-0.5 hover:from-blue-400 hover:to-blue-700 disabled:translate-y-0 disabled:opacity-50"
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                    </svg>
                    SEARCHING
                  </span>
                ) : (
                  <>
                    <Search className="w-4 h-4" />
                    SEARCH PROPERTY
                  </>
                )}
              </button>
            </div>
            </div>
            {error && (
              <div className="mt-3 flex items-center gap-2 rounded-xl border border-red-400/40 bg-red-500/20 px-4 py-2.5 backdrop-blur">
                <AlertCircle className="w-4 h-4 text-red-300 flex-shrink-0" />
                <p className="text-sm text-red-200 font-medium">{error}</p>
              </div>
            )}
          </motion.form>

          <p className="text-blue-300 text-xs mt-5">
            Don&apos;t know your TDN?{" "}
            <button
              type="button"
              onClick={() => setShowFind((v) => !v)}
              className="inline-flex items-center gap-1 font-semibold text-yellow-300 underline decoration-yellow-300/50 underline-offset-4 hover:text-yellow-200"
            >
              Find it by owner name <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </p>

          {/* ── Find my TDN panel ── */}
          {showFind && (
            <div className="max-w-2xl mx-auto mt-5 bg-white rounded-2xl p-5 shadow-2xl text-left">
              <form onSubmit={handleFind} className="flex flex-col sm:flex-row gap-3">
                <input
                  type="text"
                  className="flex-1 px-4 py-3 border border-slate-200 rounded-xl text-slate-800 text-sm outline-none focus:ring-2 focus:ring-[#1a3a6b]"
                  placeholder="Owner name (min 3 letters)"
                  value={findName}
                  onChange={(e) => { setFindName(e.target.value); setFindError(""); }}
                  aria-label="Owner name"
                />
                <input
                  type="text"
                  className="sm:w-40 px-4 py-3 border border-slate-200 rounded-xl text-slate-800 text-sm outline-none focus:ring-2 focus:ring-[#1a3a6b]"
                  placeholder="Barangay (optional)"
                  value={findBarangay}
                  onChange={(e) => setFindBarangay(e.target.value)}
                  aria-label="Barangay"
                />
                <button
                  type="submit"
                  disabled={findLoading}
                  className="bg-[#1a3a6b] text-white px-6 py-3 rounded-xl font-bold text-sm hover:bg-[#0f2a5e] transition-colors disabled:opacity-50 whitespace-nowrap"
                >
                  {findLoading ? "Finding…" : "Find"}
                </button>
              </form>

              {findError && (
                <p className="text-sm text-red-600 mt-3 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" /> {findError}
                </p>
              )}
              {findMessage && (
                <p className="text-sm text-slate-500 mt-3">{findMessage}</p>
              )}

              {findResults.length > 0 && (
                <div className="mt-4 divide-y divide-slate-100 border border-slate-100 rounded-xl overflow-hidden">
                  {findResults.map((r, i) => (
                    <button
                      key={i}
                      onClick={() => router.push(`/property/${encodeURIComponent(r.td_number)}`)}
                      className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 transition-colors text-left"
                    >
                      <div>
                        <p className="font-bold text-slate-800 text-sm">{r.owner_name}</p>
                        <p className="text-xs text-slate-400">
                          {r.barangay || "—"} · {r.kind || "Property"} · TD {r.td_tail}
                        </p>
                      </div>
                      <span className="text-[#1a3a6b] text-sm font-semibold">View →</span>
                    </button>
                  ))}
                </div>
              )}
              <p className="text-xs text-slate-400 mt-3">
                Results are masked for privacy. Only you can recognize your own record.
              </p>
            </div>
          )}
        </div>
      </motion.section>

      {/* ── Feature cards ── */}
      <section className="mx-auto w-full max-w-6xl px-4 py-12">
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {informationCards.map(({ title, desc, icon: Icon, color, bg }, index) => (
            <motion.div
              key={title}
              className="group relative overflow-hidden rounded-3xl border border-white/80 bg-white/90 p-6 shadow-[0_22px_55px_rgba(15,23,42,0.10)] backdrop-blur transition-all hover:-translate-y-1 hover:shadow-[0_28px_65px_rgba(15,23,42,0.16)]"
              initial={{ y: 20, opacity: 0 }}
              whileInView={{ y: 0, opacity: 1 }}
              viewport={{ once: true, amount: 0.35 }}
              transition={{ delay: index * 0.08, duration: 0.45, ease: "easeOut" }}
            >
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-blue-500 via-yellow-300 to-emerald-400 opacity-0 transition-opacity group-hover:opacity-100" />
              <div className={`mb-5 flex h-14 w-14 items-center justify-center rounded-2xl ${bg} shadow-lg shadow-slate-200/70`}>
                <Icon className={`h-7 w-7 ${color}`} />
              </div>
              <h3 className="text-lg font-black text-slate-900">{title}</h3>
              <p className="mt-3 text-sm leading-7 text-slate-600">{desc}</p>
              <div className="mt-6 flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 text-slate-500 transition-all group-hover:border-blue-200 group-hover:bg-blue-50 group-hover:text-blue-700">
                <ArrowRight className="h-4 w-4" />
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ── Notice banner ── */}
      <section className="max-w-5xl mx-auto px-4 pb-6 w-full">
        <div className="bg-yellow-50 border border-yellow-200 rounded-2xl p-5 flex flex-col sm:flex-row items-start sm:items-center gap-4">
          <div className="w-10 h-10 bg-yellow-400 rounded-xl flex items-center justify-center flex-shrink-0">
            <Clock className="w-5 h-5 text-yellow-900" />
          </div>
          <div>
            <p className="font-bold text-yellow-900 text-sm">Payment Deadline Reminder</p>
            <p className="text-yellow-800 text-sm mt-0.5">
              Annual RPT payments are due on <strong>January 31</strong> of each year.
              Payments made by <strong>March 31</strong> qualify for a <strong>10% prompt payment discount</strong>.
              Advance payments (prior year) qualify for a <strong>20% discount</strong>.
              Late payments are subject to a <strong>2% monthly penalty</strong>.
            </p>
          </div>
        </div>
      </section>

      {/* ── How to use ── */}
      <section className="max-w-5xl mx-auto px-4 pb-12 w-full">
        <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-8">
          <h3 className="font-extrabold text-slate-800 text-lg mb-6">How to Use This Portal</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            {[
              { step: "1", title: "Enter Your TDN", desc: "Type your Tax Declaration Number (e.g. 06-0012-01379) in the search box above. You can find this on your tax receipt or assessment notice." },
              { step: "2", title: "View Your Record", desc: "See your property details, assessed value, payment history, and current balance — all in one place." },
              { step: "3", title: "Visit the Office", desc: "To make payments or correct records, visit the Municipal Treasury Office. Bring your TDN and a valid ID." },
            ].map(({ step, title, desc }) => (
              <div key={step} className="flex gap-4">
                <div className="w-9 h-9 rounded-full bg-[#1a3a6b] text-white font-bold text-sm flex items-center justify-center flex-shrink-0">
                  {step}
                </div>
                <div>
                  <p className="font-bold text-slate-800 text-sm mb-1">{title}</p>
                  <p className="text-sm text-slate-500 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Contact ── */}
      <section className="bg-[#1a3a6b] text-white py-10 px-4">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
          <div>
            <p className="font-bold text-lg">Need Help?</p>
            <p className="text-blue-200 text-sm mt-1">
              Visit the Municipal Treasury Office of Dipaculao, Aurora during office hours.
            </p>
            <p className="text-blue-300 text-xs mt-1">
              Monday – Friday &nbsp;|&nbsp; 8:00 AM – 5:00 PM &nbsp;|&nbsp; Excluding Holidays
            </p>
          </div>
          <div className="flex items-center gap-3 bg-white/10 border border-white/20 rounded-xl px-5 py-3">
            <Phone className="w-5 h-5 text-yellow-300" />
            <div>
              <p className="text-xs text-blue-300">Municipal Treasury Office</p>
              <p className="font-bold text-sm">Dipaculao, Aurora</p>
            </div>
          </div>
        </div>
      </section>

    </div>
  );
}
