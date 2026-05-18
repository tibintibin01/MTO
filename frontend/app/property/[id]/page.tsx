"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { 
  ArrowLeft, 
  FileText, 
  CheckCircle2, 
  AlertCircle, 
  CreditCard,
  Building2,
  MapPin
} from "lucide-react";
import Link from "next/link";

export default function PropertyDetail() {
  const params = useParams();
  const id = params.id as string;
  
  const [data, setData] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function fetchData() {
      try {
        // Fetch property details
        const res = await fetch(`/api/v1/public/property/${id}`);
        if (!res.ok) throw new Error("Property not found or access denied.");
        const json = await res.json();
        setData(json);

        // Fetch history
        const hRes = await fetch(`/api/v1/public/property/${id}/history`);
        if (hRes.ok) {
            setHistory(await hRes.json());
        }
      } catch (err: any) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [id]);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-20 text-center">
        <div className="animate-pulse flex flex-col items-center">
          <div className="h-8 w-64 bg-slate-200 rounded mb-4"></div>
          <div className="h-4 w-48 bg-slate-100 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-20 text-center">
        <AlertCircle className="w-16 h-16 text-red-500 mx-auto mb-4" />
        <h2 className="text-2xl font-bold text-slate-900 mb-2">Search Failed</h2>
        <p className="text-slate-500 mb-8">{error}</p>
        <Link href="/" className="text-[#1f4e78] font-bold hover:underline flex items-center justify-center gap-2">
          <ArrowLeft className="w-4 h-4" /> Try another search
        </Link>
      </div>
    );
  }

  const isDelinquent = data.status === "DELINQUENT";

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <Link href="/" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-[#1f4e78] mb-8 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Back to Search
      </Link>

      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden mb-8">
        <div className={`px-6 py-4 flex items-center justify-between ${isDelinquent ? 'bg-orange-50' : 'bg-green-50'}`}>
          <div className="flex items-center gap-3">
            {isDelinquent ? (
              <AlertCircle className="text-orange-600 w-6 h-6" />
            ) : (
              <CheckCircle2 className="text-green-600 w-6 h-6" />
            )}
            <span className={`font-bold text-sm uppercase tracking-wider ${isDelinquent ? 'text-orange-800' : 'text-green-800'}`}>
              {isDelinquent ? "PAYMENT REQUIRED" : "ACCOUNT UPDATED"}
            </span>
          </div>
          <span className="text-xs text-slate-500 font-medium">As of {new Date().toLocaleDateString()}</span>
        </div>

        <div className="p-6 sm:p-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8">
            <div>
              <h1 className="text-3xl font-extrabold text-slate-900 mb-1">{data.td_number}</h1>
              <p className="text-slate-500 font-medium mb-6">Property Index Number: {data.pin}</p>
              
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                    <Building2 className="w-5 h-5 text-slate-400 mt-0.5" />
                    <div>
                        <p className="text-xs text-slate-400 font-bold uppercase tracking-tight">Owner</p>
                        <p className="text-slate-700 font-medium">{data.owner_name}</p>
                    </div>
                </div>
                <div className="flex items-start gap-3">
                    <MapPin className="w-5 h-5 text-slate-400 mt-0.5" />
                    <div>
                        <p className="text-xs text-slate-400 font-bold uppercase tracking-tight">Location</p>
                        <p className="text-slate-700 font-medium">{data.location}</p>
                    </div>
                </div>
              </div>
            </div>

            <div className="bg-slate-50 rounded-xl p-6 border border-slate-100 flex flex-col justify-center">
                <p className="text-xs text-slate-400 font-bold uppercase tracking-tight mb-1">Current Assessed Value</p>
                <p className="text-4xl font-black text-[#1f4e78]">P {data.assessed_value.toLocaleString()}</p>
                <div className="mt-4 inline-flex items-center gap-2 bg-white px-3 py-1 rounded-full border border-slate-200 w-fit">
                    <div className="w-2 h-2 rounded-full bg-blue-500"></div>
                    <span className="text-xs font-bold text-slate-600 uppercase">{data.kind}</span>
                </div>
            </div>
          </div>
        </div>
      </div>

      <div className="mb-12">
        <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-6">
          <FileText className="w-5 h-5 text-[#1f4e78]" />
          Recent Payment History
        </h3>

        
        {history.length > 0 ? (
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <table className="w-full text-left text-sm">
                <thead>
                    <tr className="bg-slate-50 border-b border-slate-200">
                        <th className="px-6 py-4 font-bold text-slate-700">Period</th>
                        <th className="px-6 py-4 font-bold text-slate-700">OR Number</th>
                        <th className="px-6 py-4 font-bold text-slate-700">Date Paid</th>
                        <th className="px-6 py-4 font-bold text-slate-700 text-right">Amount</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                    {history.map((p, i) => (
                        <tr key={i} className="hover:bg-slate-50 transition-colors">
                            <td className="px-6 py-4 font-bold text-[#1f4e78]">{p.period}</td>
                            <td className="px-6 py-4 text-slate-600">{p.or_number}</td>
                            <td className="px-6 py-4 text-slate-500">{p.date_paid}</td>
                            <td className="px-6 py-4 text-right font-bold text-slate-900">P {p.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-slate-50 rounded-xl p-12 text-center border-2 border-dashed border-slate-200">
            <FileText className="w-12 h-12 text-slate-300 mx-auto mb-4" />
            <p className="text-slate-500">No payment records found for this property.</p>
          </div>
        )}
      </div>

      <div className="bg-[#1f4e78] rounded-2xl p-8 text-white flex flex-col sm:flex-row items-center justify-between gap-6">
        <div>
            <h4 className="text-xl font-bold mb-1">Need a Certified Copy?</h4>
            <p className="text-blue-100 text-sm">Visit the Municipal Treasury Office with your physical ID and current TDN.</p>
        </div>
        <button className="bg-white text-[#1f4e78] px-6 py-3 rounded-lg font-bold hover:bg-blue-50 transition-colors whitespace-nowrap">
            CONTACT OFFICE
        </button>
      </div>
    </div>
  );
}
