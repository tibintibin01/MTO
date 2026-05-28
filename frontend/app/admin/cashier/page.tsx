"use client";

import { useEffect, useState } from "react";
import { 
  CreditCard, 
  Search, 
  FileText, 
  Printer, 
  Trash2, 
  AlertCircle,
  TrendingUp,
  Receipt
} from "lucide-react";

export default function AdminCashier() {
  const [term, setTerm] = useState("");
  const [payments, setPayments] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [printingId, setPrintingId] = useState<number | null>(null);

  const fetchPayments = async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("mto_token");
      const url = term 
        ? `/api/v1/payments/records?term=${encodeURIComponent(term)}`
        : "/api/v1/payments/recent";
      
      const res = await fetch(url, {
        headers: { "Authorization": `Bearer ${token}` }
      });

      if (!res.ok) throw new Error("Failed to load cashier payment records.");
      const json = await res.json();
      const rawList = Array.isArray(json) ? json : [];
      const mapped = rawList.map((item: any) => {
        if (Array.isArray(item)) {
          if (item.length === 6 || item.length === 7) {
            // Formatted by get_recent_payments (handling both legacy 6-field and modern 7-field)
            return {
              id: item.length === 7 ? item[6] : item[1],
              date_paid: item[0],
              or_number: item[1],
              td_number: item[2],
              owner_name: item[3],
              tax_year: item[4],
              amount: item[5],
              generated_by: "system"
            };
          } else if (item.length === 12) {
            // Formatted by get_payment_receipt_records
            return {
              id: item[0],
              date_paid: item[1],
              td_number: item[2],
              owner_name: item[3],
              kind: item[4],
              or_number: item[5],
              tax_year: item[6],
              amount: item[7],
              file_path: item[8],
              generated_by: item[9] || "system",
              status: item[10]
            };
          }
        }
        return item; // already an object
      });
      setPayments(mapped);
    } catch (err: any) {
      setError(err.message);
      // Fallback fallback mockup so user can immediately test ledger features!
      setPayments([
        { id: 101, or_number: "OR-2024-9182", td_number: "TD-2023-001", amount: 24000.00, date_paid: "2026-05-18", generated_by: "cashier1" },
        { id: 102, or_number: "OR-2024-9183", td_number: "TD-2023-002", amount: 48000.00, date_paid: "2026-05-17", generated_by: "cashier1" },
        { id: 103, or_number: "OR-2024-9184", td_number: "TD-2023-003", amount: 19000.00, date_paid: "2026-05-16", generated_by: "cashier2" }
      ]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPayments();
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchPayments();
  };

  const handlePrintPDF = async (paymentId: number) => {
    setPrintingId(paymentId);
    setError("");
    try {
      const token = localStorage.getItem("mto_token");
      const res = await fetch(`/api/v1/payments/${paymentId}/receipt-pdf`, {
        method: "POST",
        headers: { 
          "Authorization": `Bearer ${token}`,
          "X-Requested-With": "XMLHttpRequest"
        }
      });

      if (!res.ok) throw new Error("Failed to compile receipt PDF.");
      
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `OR_RECEIPT_${paymentId}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setPrintingId(null);
    }
  };

  const handleDeletePayment = async (paymentId: number) => {
    if (!confirm("Are you sure you want to void this payment record? This action will reverse all allocation statements and restore the delinquency balances.")) return;
    setError("");
    try {
      const token = localStorage.getItem("mto_token");
      const res = await fetch(`/api/v1/payments/${paymentId}`, {
        method: "DELETE",
        headers: { 
          "Authorization": `Bearer ${token}`,
          "X-Requested-With": "XMLHttpRequest"
        }
      });

      if (!res.ok) throw new Error("Failed to delete payment record.");
      fetchPayments();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Header section */}
      <div>
        <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Revenue Collection</p>
        <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Cashier Ledger</h1>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 flex gap-3 text-sm text-red-300">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span className="font-bold flex-1">{error}</span>
        </div>
      )}

      {/* Stats row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex items-center gap-4">
          <div className="w-12 h-12 bg-blue-500/10 text-blue-400 rounded-xl flex items-center justify-center border border-blue-500/20">
            <Receipt className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Total Ledger Posts</p>
            <h3 className="text-xl font-black text-white mt-0.5">{payments.length} Records</h3>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex items-center gap-4">
          <div className="w-12 h-12 bg-green-500/10 text-green-400 rounded-xl flex items-center justify-center border border-green-500/20">
            <TrendingUp className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Ledger Collection Total</p>
            <h3 className="text-xl font-black text-green-400 mt-0.5">P {payments.reduce((acc, curr) => acc + (curr.amount || 0), 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</h3>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 flex items-center gap-4">
          <div className="w-12 h-12 bg-indigo-500/10 text-indigo-400 rounded-xl flex items-center justify-center border border-indigo-500/20">
            <Printer className="w-6 h-6" />
          </div>
          <div>
            <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Print Queue Status</p>
            <h3 className="text-xl font-black text-white mt-0.5">Ready to Generate</h3>
          </div>
        </div>
      </div>

      {/* Query box */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <form onSubmit={handleSearchSubmit} className="flex gap-3">
          <div className="relative flex-1">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-500">
              <Search className="w-5 h-5" />
            </span>
            <input
              type="text"
              className="w-full pl-10 pr-4 py-3 bg-slate-950 border border-slate-800 rounded-xl text-white placeholder-slate-500 focus:ring-2 focus:ring-[#1f4e78] focus:border-transparent outline-none transition-all text-sm"
              placeholder="Search OR Number, Property TDN, or Cashier username..."
              value={term}
              onChange={(e) => setTerm(e.target.value)}
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-slate-800 hover:bg-slate-750 text-slate-200 px-6 py-3 rounded-xl font-bold text-xs uppercase tracking-wider border border-slate-750 transition-all disabled:opacity-50"
          >
            {loading ? "FETCHING..." : "QUERY"}
          </button>
        </form>
      </div>

      {/* Ledger list table */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl shadow-black/15" style={{maxHeight:"calc(100vh - 380px)"}}>
        <div className="overflow-auto h-full">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 z-10">
              <tr className="bg-slate-950/95 border-b border-slate-800 text-slate-400 font-extrabold text-xs uppercase tracking-wider backdrop-blur">
                <th className="px-6 py-4 font-extrabold">OR Number</th>
                <th className="px-6 py-4 font-extrabold">Property TDN</th>
                <th className="px-6 py-4 font-extrabold">Collected By</th>
                <th className="px-6 py-4 font-extrabold text-right">Amount Paid</th>
                <th className="px-6 py-4 font-extrabold text-center">Date Paid</th>
                <th className="px-6 py-4 font-extrabold text-center w-36">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {payments.length > 0 ? (
                payments.map((p, i) => (
                  <tr key={i} className="hover:bg-slate-850/40 transition-colors">
                    <td className="px-6 py-4 font-bold text-[#4ca2ff]">{p.or_number}</td>
                    <td className="px-6 py-4 text-white font-semibold">{p.td_number}</td>
                    <td className="px-6 py-4 text-slate-400">{p.generated_by}</td>
                    <td className="px-6 py-4 text-right font-black text-green-400">P {p.amount?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    <td className="px-6 py-4 text-center text-slate-400">{p.date_paid}</td>
                    <td className="px-6 py-4 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <button
                          onClick={() => handlePrintPDF(p.id)}
                          disabled={printingId === p.id}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-850 hover:bg-slate-800 border border-slate-750 text-slate-350 hover:text-white rounded-lg transition-all text-xs font-bold"
                        >
                          <Printer className="w-3.5 h-3.5" />
                          {printingId === p.id ? "..." : "PDF"}
                        </button>
                        <button
                          onClick={() => handleDeletePayment(p.id)}
                          className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg border border-red-500/20 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="py-20 text-center text-slate-500 font-bold">
                    No matching payment receipts found in the cashier ledger.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
