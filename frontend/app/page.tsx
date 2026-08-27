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
  Eye,
  Landmark,
  MapPin,
  Search,
  Shield,
} from "lucide-react";

const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{1,49}$/;

type PropertyAccountMatch = {
  account_key: string;
  owner_name: string;
  pin: string | null;
  barangay: string | null;
  location: string | null;
  kind: string | null;
};

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
  const [duplicateMatches, setDuplicateMatches] = useState<PropertyAccountMatch[]>([]);

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
    setDuplicateMatches([]);
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
      if (res.status === 409) {
        const payload = await res.json().catch(() => null);
        const matches = Array.isArray(payload?.matches) ? payload.matches : [];
        if (payload?.code === "MULTIPLE_PROPERTY_ACCOUNTS" && matches.length > 1) {
          setDuplicateMatches(matches);
          return;
        }
        setError(
          payload?.detail || "More than one property account matches this search. Please contact the Municipal Treasury Office.",
        );
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
          className="absolute left-[10%] top-[24%] hidden h-24 w-24 lg:block"
          style={{ transformStyle: "preserve-3d", perspective: 700 }}
          animate={{ y: [0, -13, 0], rotateX: [4, -5, 4], rotateY: [-10, 8, -10] }}
          transition={{ duration: 6.5, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden="true"
        >
          <div className="absolute inset-2 translate-x-2 translate-y-3 rounded-[1.7rem] bg-cyan-950/70 blur-md" />
          <div className="absolute inset-0 rounded-[1.75rem] border border-cyan-100/35 bg-gradient-to-br from-white/25 via-cyan-300/10 to-blue-950/50 shadow-[inset_0_1px_1px_rgba(255,255,255,0.55),inset_0_-14px_28px_rgba(2,12,32,0.35),0_24px_50px_rgba(1,8,24,0.48),0_0_28px_rgba(103,232,249,0.18)] backdrop-blur-xl" />
          <div className="absolute inset-[11px] flex items-center justify-center rounded-[1.3rem] border border-cyan-100/25 bg-gradient-to-br from-cyan-200/20 via-blue-500/10 to-blue-950/45 shadow-[inset_0_2px_8px_rgba(255,255,255,0.22),0_9px_18px_rgba(1,8,24,0.35)]">
            <MapPin className="absolute h-10 w-10 translate-x-1 translate-y-1 text-blue-950/65" strokeWidth={2.4} />
            <MapPin className="relative h-10 w-10 text-cyan-100 drop-shadow-[0_0_12px_rgba(165,243,252,0.75)]" strokeWidth={2.4} />
            <span className="absolute left-3 top-2 h-1.5 w-8 rounded-full bg-white/45 blur-[1px]" />
          </div>
        </motion.div>
        <motion.div
          className="absolute right-[10%] top-[28%] hidden h-24 w-24 lg:block"
          style={{ transformStyle: "preserve-3d", perspective: 700 }}
          animate={{ y: [0, 13, 0], rotateX: [-4, 5, -4], rotateY: [10, -8, 10] }}
          transition={{ duration: 7.5, repeat: Infinity, ease: "easeInOut" }}
          aria-hidden="true"
        >
          <div className="absolute inset-2 translate-x-2 translate-y-3 rounded-[1.7rem] bg-amber-950/60 blur-md" />
          <div className="absolute inset-0 rounded-[1.75rem] border border-amber-100/40 bg-gradient-to-br from-white/25 via-amber-300/10 to-blue-950/55 shadow-[inset_0_1px_1px_rgba(255,255,255,0.55),inset_0_-14px_28px_rgba(2,12,32,0.35),0_24px_50px_rgba(1,8,24,0.48),0_0_28px_rgba(253,224,71,0.18)] backdrop-blur-xl" />
          <div className="absolute inset-[11px] flex items-center justify-center rounded-[1.3rem] border border-amber-100/30 bg-gradient-to-br from-amber-100/25 via-yellow-400/10 to-blue-950/45 shadow-[inset_0_2px_8px_rgba(255,255,255,0.22),0_9px_18px_rgba(1,8,24,0.35)]">
            <Landmark className="absolute h-10 w-10 translate-x-1 translate-y-1 text-blue-950/65" strokeWidth={2.3} />
            <Landmark className="relative h-10 w-10 text-amber-100 drop-shadow-[0_0_12px_rgba(253,230,138,0.75)]" strokeWidth={2.3} />
            <span className="absolute left-3 top-2 h-1.5 w-8 rounded-full bg-white/45 blur-[1px]" />
          </div>
        </motion.div>
        <div className="absolute inset-x-0 bottom-0 h-px bg-white/25" aria-hidden="true" />
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
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setError("");
                    setDuplicateMatches([]);
                  }}
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
            {duplicateMatches.length > 0 && (
              <div className="mt-4 overflow-hidden rounded-2xl border border-amber-200/60 bg-white text-left shadow-2xl">
                <div className="border-b border-amber-100 bg-amber-50 px-5 py-4">
                  <p className="font-black text-slate-900">
                    {duplicateMatches.length} separate property accounts use this TDN
                  </p>
                  <p className="mt-1 text-sm text-slate-600">
                    Select the correct owner and property. Billing and payment history will remain separate.
                  </p>
                </div>
                <div className="divide-y divide-slate-100">
                  {duplicateMatches.map((match) => (
                    <button
                      key={match.account_key}
                      type="button"
                      onClick={() => router.push(
                        `/property/${encodeURIComponent(query.trim())}?account=${encodeURIComponent(match.account_key)}`,
                      )}
                      className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-blue-50"
                    >
                      <div>
                        <p className="font-bold text-slate-900">{match.owner_name}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {match.barangay || match.location || "Location unavailable"}
                          {" · "}{match.kind || "Property"}
                          {match.pin ? ` · PIN ${match.pin}` : ""}
                        </p>
                      </div>
                      <span className="whitespace-nowrap text-sm font-bold text-blue-800">Select →</span>
                    </button>
                  ))}
                </div>
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
                      onClick={() => {
                        const account = r.account_key
                          ? `?account=${encodeURIComponent(r.account_key)}`
                          : "";
                        router.push(`/property/${encodeURIComponent(r.td_number)}${account}`);
                      }}
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

      {/* ── Official payment advisory ── */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-7">
        <motion.div
          className="relative overflow-hidden rounded-2xl border border-amber-300/80 bg-gradient-to-r from-amber-50 via-yellow-50 to-white px-5 py-5 shadow-[0_14px_34px_rgba(146,64,14,0.09)] sm:px-6"
          initial={{ opacity: 0, y: 16 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, amount: 0.4 }}
        >
          <div className="absolute inset-y-0 left-0 w-1.5 bg-gradient-to-b from-amber-400 to-yellow-500" />
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-2xl border border-amber-200 bg-gradient-to-br from-yellow-300 to-amber-500 text-amber-950 shadow-[0_8px_18px_rgba(245,158,11,0.28)]">
              <Clock className="h-6 w-6" />
            </div>
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-black text-amber-950">Payment Deadline Reminder</p>
                <span className="rounded-full border border-amber-200 bg-white/80 px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest text-amber-700">Official advisory</span>
              </div>
              <p className="mt-1.5 text-sm leading-6 text-amber-900/85">
                Annual RPT payments are due on <strong>January 31</strong>. Payments made by <strong>March 31</strong> qualify for a <strong>10% prompt payment discount</strong>; advance payments qualify for <strong>20%</strong>. Late payments are subject to a <strong>2% monthly penalty</strong>.
              </p>
            </div>
          </div>
        </motion.div>
      </section>

      {/* ── How to use ── */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-14">
        <div className="relative overflow-hidden rounded-3xl border border-white bg-white/90 p-6 shadow-[0_22px_55px_rgba(15,23,42,0.10)] backdrop-blur sm:p-8">
          <div className="absolute inset-x-12 top-0 h-px bg-gradient-to-r from-transparent via-blue-400/70 to-transparent" />
          <div className="mb-7 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-blue-600">Three simple steps</p>
              <h3 className="mt-1 text-xl font-black text-slate-900">How to Use This Portal</h3>
            </div>
            <p className="text-xs text-slate-400">Secure, read-only property inquiry</p>
          </div>
          <div className="relative grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="absolute left-[16%] right-[16%] top-7 hidden h-px bg-gradient-to-r from-blue-200 via-amber-200 to-emerald-200 sm:block" />
            {[
              { step: "01", title: "Enter Your TDN", desc: "Enter the Tax Declaration Number shown on your tax receipt or assessment notice.", icon: Search, tone: "text-blue-700", surface: "from-blue-50 to-white", ring: "border-blue-200" },
              { step: "02", title: "View Your Record", desc: "Review the assessment, official payment history, and current outstanding balance.", icon: Eye, tone: "text-amber-700", surface: "from-amber-50 to-white", ring: "border-amber-200" },
              { step: "03", title: "Visit the Office", desc: "For payments or corrections, bring your TDN and a valid ID to the Treasury Office.", icon: Landmark, tone: "text-emerald-700", surface: "from-emerald-50 to-white", ring: "border-emerald-200" },
            ].map(({ step, title, desc, icon: Icon, tone, surface, ring }, index) => (
              <motion.div
                key={step}
                className={`group relative rounded-2xl border ${ring} bg-gradient-to-br ${surface} p-5 shadow-[0_10px_24px_rgba(15,23,42,0.06)]`}
                initial={{ opacity: 0, y: 14 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true, amount: 0.4 }}
                transition={{ delay: index * 0.08 }}
                whileHover={{ y: -4 }}
              >
                <div className="mb-5 flex items-center justify-between">
                  <div className={`relative z-10 flex h-14 w-14 items-center justify-center rounded-2xl border ${ring} bg-white ${tone} shadow-[0_8px_18px_rgba(15,23,42,0.10)]`}>
                    <Icon className="h-6 w-6" />
                  </div>
                  <span className="text-xs font-black tracking-widest text-slate-300">{step}</span>
                </div>
                <p className="text-sm font-black text-slate-900">{title}</p>
                <p className="mt-2 text-sm leading-6 text-slate-500">{desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

    </div>
  );
}
