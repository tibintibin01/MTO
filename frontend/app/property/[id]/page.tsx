"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  FileText,
  CheckCircle2,
  AlertCircle,
  Building2,
  MapPin,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useToast } from "../../components/ToastProvider";

// ---------------------------------------------------------------------------
// Loading skeleton — mirrors the actual page layout so there's no layout shift
// ---------------------------------------------------------------------------
function PropertySkeleton() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-8 animate-pulse" aria-busy="true" aria-label="Loading property data">
      {/* Back link */}
      <div className="h-4 w-28 bg-slate-200 rounded mb-8" />

      {/* Status bar */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden mb-8">
        <div className="h-14 bg-slate-100" />
        <div className="p-6 sm:p-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
            <div className="space-y-3">
              <div className="h-8 w-48 bg-slate-200 rounded" />
              <div className="h-4 w-36 bg-slate-100 rounded" />
              <div className="h-4 w-56 bg-slate-100 rounded mt-4" />
              <div className="h-4 w-44 bg-slate-100 rounded" />
            </div>
            <div className="bg-slate-50 rounded-xl p-6 border border-slate-100 space-y-3">
              <div className="h-3 w-32 bg-slate-200 rounded" />
              <div className="h-10 w-40 bg-slate-200 rounded" />
              <div className="h-6 w-24 bg-slate-100 rounded-full" />
            </div>
          </div>
        </div>
      </div>

      {/* Payment history table */}
      <div className="h-5 w-40 bg-slate-200 rounded mb-6" />
      <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="flex gap-4 px-6 py-4 border-b border-slate-100 last:border-0">
            <div className="h-4 w-16 bg-slate-100 rounded" />
            <div className="h-4 w-24 bg-slate-100 rounded" />
            <div className="h-4 w-20 bg-slate-100 rounded" />
            <div className="h-4 w-20 bg-slate-100 rounded ml-auto" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function PropertyDetail() {
  const params = useParams();
  const id = params.id as string;
  const { toast } = useToast();

  const [data, setData] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);

  const fetchData = async () => {
    setError("");
    try {
      const res = await fetch(`/api/v1/public/property/${id}`);

      if (res.status === 404) {
        setError("This property was not found. The TDN or PIN may be incorrect.");
        return;
      }
      if (res.status === 429) {
        setError("Too many requests. Please wait a moment and try again.");
        return;
      }
      if (!res.ok) {
        setError("Unable to load property data. Please try again.");
        return;
      }

      const json = await res.json();
      setData(json);

      // History is non-critical — failure is surfaced as a toast, not a page error
      try {
        const hRes = await fetch(`/api/v1/public/property/${id}/history`);
        if (hRes.ok) {
          setHistory(await hRes.json());
        } else {
          toast("Payment history could not be loaded.", "info");
        }
      } catch {
        toast("Payment history is temporarily unavailable.", "info");
      }
    } catch {
      // Network-level failure (offline, DNS, etc.)
      setError("Network error. Please check your connection and try again.");
    } finally {
      setLoading(false);
      setRetrying(false);
    }
  };

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const handleRetry = () => {
    setLoading(true);
    setRetrying(true);
    fetchData();
  };

  if (loading) return <PropertySkeleton />;

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-20 text-center">
        <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-6">
          <AlertCircle className="w-8 h-8 text-red-500" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">Could not load property</h2>
        <p className="text-slate-500 mb-8 max-w-sm mx-auto">{error}</p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-[#1f4e78] text-white rounded-lg font-semibold text-sm hover:bg-[#2c6ea1] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${retrying ? "animate-spin" : ""}`} />
            {retrying ? "Retrying..." : "Try again"}
          </button>
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-100 text-slate-700 rounded-lg font-semibold text-sm hover:bg-slate-200 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> New search
          </Link>
        </div>
      </div>
    );
  }

  const isDelinquent = data.status === "DELINQUENT";
  const isPending = data.status === "PENDING";

  // Status bar config
  const statusConfig = isDelinquent
    ? { bg: "bg-orange-50", icon: <AlertCircle className="text-orange-600 w-6 h-6" aria-hidden="true" />, label: "PAYMENT REQUIRED", labelColor: "text-orange-800" }
    : isPending
    ? { bg: "bg-slate-50", icon: <AlertCircle className="text-slate-400 w-6 h-6" aria-hidden="true" />, label: "NOT YET BILLED", labelColor: "text-slate-600" }
    : { bg: "bg-green-50", icon: <CheckCircle2 className="text-green-600 w-6 h-6" aria-hidden="true" />, label: "ACCOUNT UPDATED", labelColor: "text-green-800" };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <Link
        href="/"
        className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-[#1f4e78] mb-8 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Search
      </Link>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden mb-8">
        <div
          className={`px-6 py-4 flex items-center justify-between ${statusConfig.bg}`}
        >
          <div className="flex items-center gap-3">
            {statusConfig.icon}
            <span className={`font-bold text-sm uppercase tracking-wider ${statusConfig.labelColor}`}>
              {statusConfig.label}
            </span>
          </div>
          <span className="text-xs text-slate-500 font-medium">
            As of {new Date().toLocaleDateString()}
          </span>
        </div>

        <div className="p-6 sm:p-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
            <div>
              <h1 className="text-3xl font-extrabold text-slate-900 mb-1">{data.td_number}</h1>
              <p className="text-slate-500 font-medium mb-6">Property Index Number: {data.pin}</p>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <Building2 className="w-5 h-5 text-slate-400 mt-0.5" aria-hidden="true" />
                  <div>
                    <p className="text-xs text-slate-400 font-bold uppercase tracking-tight">Owner</p>
                    <p className="text-slate-700 font-medium">{data.owner_name}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <MapPin className="w-5 h-5 text-slate-400 mt-0.5" aria-hidden="true" />
                  <div>
                    <p className="text-xs text-slate-400 font-bold uppercase tracking-tight">Location</p>
                    <p className="text-slate-700 font-medium">{data.location}</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-slate-50 rounded-xl p-6 border border-slate-100 flex flex-col justify-center">
              <p className="text-xs text-slate-400 font-bold uppercase tracking-tight mb-1">
                Current Assessed Value
              </p>
              <p className="text-4xl font-black text-[#1f4e78]">
                ₱ {data.assessed_value.toLocaleString()}
              </p>
              <div className="mt-4 inline-flex items-center gap-2 bg-white px-3 py-1 rounded-full border border-slate-200 w-fit">
                <div className="w-2 h-2 rounded-full bg-blue-500" />
                <span className="text-xs font-bold text-slate-600 uppercase">{data.kind}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-12">
        <h2 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-6">
          <FileText className="w-5 h-5 text-[#1f4e78]" aria-hidden="true" />
          Recent Payment History
        </h2>

        {history.length > 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200">
                  <th scope="col" className="px-6 py-4 font-bold text-slate-700">Period</th>
                  <th scope="col" className="px-6 py-4 font-bold text-slate-700">OR Number</th>
                  <th scope="col" className="px-6 py-4 font-bold text-slate-700">Date Paid</th>
                  <th scope="col" className="px-6 py-4 font-bold text-slate-700 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {history.map((p, i) => (
                  <tr key={i} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-4 font-bold text-[#1f4e78]">{p.period}</td>
                    <td className="px-6 py-4 text-slate-600">{p.or_number}</td>
                    <td className="px-6 py-4 text-slate-500">{p.date_paid}</td>
                    <td className="px-6 py-4 text-right font-bold text-slate-900">
                      ₱ {p.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-slate-50 rounded-xl p-12 text-center border-2 border-dashed border-slate-200">
            <FileText className="w-12 h-12 text-slate-300 mx-auto mb-4" aria-hidden="true" />
            <p className="text-slate-500">No payment records found for this property.</p>
          </div>
        )}
      </div>

      <div className="bg-[#1f4e78] rounded-2xl p-8 text-white flex flex-col sm:flex-row items-center justify-between gap-6">
        <div>
          <h3 className="text-xl font-bold mb-1">Need a Certified Copy?</h3>
          <p className="text-blue-100 text-sm">
            Visit the Municipal Treasury Office with your physical ID and current TDN.
          </p>
        </div>
        <button className="bg-white text-[#1f4e78] px-6 py-3 rounded-lg font-bold hover:bg-blue-50 transition-colors whitespace-nowrap">
          CONTACT OFFICE
        </button>
      </div>
    </div>
  );
}

