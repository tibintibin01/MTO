"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Lock, MapPin, History } from "lucide-react";

// TD numbers follow patterns like: 06-0012-01379, TD-2023-001, or plain PIN digits
const QUERY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9\-./# ]{1,49}$/;

export default function Home() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

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
      // Verify the property exists before navigating so the user gets
      // immediate feedback rather than landing on a 404 detail page.
      const res = await fetch(`/api/v1/public/property/${encodeURIComponent(trimmed)}`);
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
    <div className="max-w-4xl mx-auto px-4 py-12 sm:py-20">
      <div className="text-center mb-12">
        <h2 className="text-3xl sm:text-4xl font-extrabold text-slate-900 tracking-tight mb-4">
          Property Treasury Search
        </h2>
        <p className="text-lg text-slate-600 max-w-2xl mx-auto">
          Enter your Tax Declaration Number (TDN) or PIN to view assessment status, payment history, and delinquency alerts.
        </p>
      </div>

      <div className="bg-white rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
        <form onSubmit={handleSearch} className="p-2 flex flex-col sm:flex-row gap-2">
          <div className="relative flex-1">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Search className="h-5 w-5 text-slate-400" />
            </div>
            <input
              type="text"
              className="block w-full pl-11 pr-4 py-4 border-none bg-slate-50 focus:ring-2 focus:ring-[#1f4e78] rounded-xl text-lg"
              placeholder="e.g. 06-0012-01379"
              value={query}
              onChange={(e) => { setQuery(e.target.value); setError(""); }}
              aria-label="Tax Declaration Number or PIN"
              aria-describedby={error ? "search-error" : undefined}
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-[#1f4e78] text-white px-8 py-4 rounded-xl font-bold text-lg hover:bg-[#2c6ea1] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
          >
            {loading ? "SEARCHING..." : "SEARCH PROPERTY"}
          </button>
        </form>
        {error && (
          <p id="search-error" role="alert" className="px-4 pb-3 text-sm text-red-600 font-medium">
            {error}
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 mt-16">
        <div className="p-6 bg-white rounded-xl shadow-sm border border-slate-100 text-center">
          <div className="w-12 h-12 bg-blue-50 text-[#1f4e78] rounded-full flex items-center justify-center mx-auto mb-4">
            <Lock className="w-6 h-6" />
          </div>
          <h3 className="font-bold text-slate-900 mb-2">Secure Access</h3>
          <p className="text-sm text-slate-500">Data is transmitted over an encrypted HTTPS connection.</p>
        </div>
        <div className="p-6 bg-white rounded-xl shadow-sm border border-slate-100 text-center">
          <div className="w-12 h-12 bg-orange-50 text-orange-600 rounded-full flex items-center justify-center mx-auto mb-4">
            <History className="w-6 h-6" />
          </div>
          <h3 className="font-bold text-slate-900 mb-2">Payment History</h3>
          <p className="text-sm text-slate-500">View your official payment records and tax periods.</p>
        </div>
        <div className="p-6 bg-white rounded-xl shadow-sm border border-slate-100 text-center">
          <div className="w-12 h-12 bg-green-50 text-green-600 rounded-full flex items-center justify-center mx-auto mb-4">
            <MapPin className="w-6 h-6" />
          </div>
          <h3 className="font-bold text-slate-900 mb-2">Assessment Data</h3>
          <p className="text-sm text-slate-500">Real-time property classification and assessed values.</p>
        </div>
      </div>
    </div>
  );
}
