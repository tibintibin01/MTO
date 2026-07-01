"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Shield, FileText, MapPin, Clock, Phone, AlertCircle } from "lucide-react";

const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{1,49}$/;

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
      <section className="bg-gradient-to-br from-[#1a3a6b] via-[#1f4e78] to-[#0f2a5e] text-white py-16 px-4">
        <div className="max-w-3xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-yellow-400 text-[#0f2a5e] text-xs font-bold px-4 py-1.5 rounded-full mb-6 tracking-widest uppercase">
            Official Government Portal
          </div>
          <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight mb-4 leading-tight">
            Real Property Tax<br />
            <span className="text-yellow-300">Inquiry Portal</span>
          </h2>
          <p className="text-blue-200 text-base sm:text-lg max-w-xl mx-auto mb-10">
            Enter your Tax Declaration Number (TDN) or PIN to view your property&apos;s
            assessment, payment history, and outstanding balance.
          </p>

          {/* Search box */}
          <form onSubmit={handleSearch} className="max-w-2xl mx-auto">
            <div className="flex flex-col sm:flex-row gap-3 bg-white rounded-2xl p-2 shadow-2xl">
              <div className="relative flex-1">
                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                  <Search className="h-5 w-5 text-slate-400" />
                </div>
                <input
                  type="text"
                  className="block w-full pl-11 pr-4 py-3.5 border-none bg-transparent focus:ring-0 text-slate-800 text-base placeholder-slate-400 outline-none"
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
                className="bg-[#1a3a6b] text-white px-8 py-3.5 rounded-xl font-bold text-sm tracking-wide hover:bg-[#0f2a5e] transition-all flex items-center justify-center gap-2 disabled:opacity-50 whitespace-nowrap"
              >
                {loading ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/>
                    </svg>
                    SEARCHING...
                  </span>
                ) : (
                  <>
                    <Search className="w-4 h-4" />
                    SEARCH PROPERTY
                  </>
                )}
              </button>
            </div>
            {error && (
              <div className="flex items-center gap-2 mt-3 bg-red-500/20 border border-red-400/40 rounded-xl px-4 py-2.5">
                <AlertCircle className="w-4 h-4 text-red-300 flex-shrink-0" />
                <p className="text-sm text-red-200 font-medium">{error}</p>
              </div>
            )}
          </form>

          <p className="text-blue-300 text-xs mt-5">
            Don&apos;t know your TDN?{" "}
            <button
              type="button"
              onClick={() => setShowFind((v) => !v)}
              className="text-yellow-300 font-semibold underline hover:text-yellow-200"
            >
              Find it by owner name
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
      </section>

      {/* ── Feature cards ── */}
      <section className="max-w-5xl mx-auto px-4 py-12 w-full">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 flex flex-col items-start gap-3 hover:shadow-md transition-shadow">
            <div className="w-11 h-11 bg-blue-50 rounded-xl flex items-center justify-center">
              <Shield className="w-5 h-5 text-[#1a3a6b]" />
            </div>
            <h3 className="font-bold text-slate-800">Secure Access</h3>
            <p className="text-sm text-slate-500 leading-relaxed">
              Data is transmitted over an encrypted connection. Your property information is protected under RA 10173.
            </p>
          </div>
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 flex flex-col items-start gap-3 hover:shadow-md transition-shadow">
            <div className="w-11 h-11 bg-yellow-50 rounded-xl flex items-center justify-center">
              <FileText className="w-5 h-5 text-yellow-600" />
            </div>
            <h3 className="font-bold text-slate-800">Payment History</h3>
            <p className="text-sm text-slate-500 leading-relaxed">
              View your official OR numbers, tax years covered, amounts paid, and outstanding balances. Data available from 2023.
            </p>
          </div>
          <div className="bg-white rounded-2xl shadow-sm border border-slate-100 p-6 flex flex-col items-start gap-3 hover:shadow-md transition-shadow">
            <div className="w-11 h-11 bg-green-50 rounded-xl flex items-center justify-center">
              <MapPin className="w-5 h-5 text-green-600" />
            </div>
            <h3 className="font-bold text-slate-800">Assessment Data</h3>
            <p className="text-sm text-slate-500 leading-relaxed">
              Check your property&apos;s assessed value, classification, lot number, and barangay location in real time.
            </p>
          </div>
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
