"use client";

import { useEffect, useState, useCallback } from "react";
import {
  CheckCircle2,
  Search,
  MapPin,
  Download,
  RefreshCw,
  ChevronRight,
  BarChart3,
  Users,
  TrendingUp,
  Filter,
} from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────────

interface BarangaySummary {
  barangay: string;
  total_properties: number;
  compliant_count: number;
  delinquent_count: number;
  compliance_rate: number;
  collected_from_compliant: number;
}

interface CompliantProperty {
  id: number;
  td_number: string;
  owner_name: string;
  location: string;
  barangay: string;
  kind_of_property: string;
  total_due: number;
  total_paid: number;
  last_paid: string | null;
  last_or: string | null;
  years_covered: number;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  "₱ " + n.toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function RateBadge({ rate }: { rate: number }) {
  const color =
    rate >= 80
      ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
      : rate >= 50
      ? "text-yellow-400 bg-yellow-500/10 border-yellow-500/20"
      : "text-red-400 bg-red-500/10 border-red-500/20";
  return (
    <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full uppercase border ${color}`}>
      {rate.toFixed(1)}%
    </span>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function CompliantPropertiesPage() {
  const [summary, setSummary] = useState<BarangaySummary[]>([]);
  const [properties, setProperties] = useState<CompliantProperty[]>([]);
  const [selectedBarangay, setSelectedBarangay] = useState<string>("ALL");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingProps, setLoadingProps] = useState(false);
  const [cursor, setCursor] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");

  // ── Fetch barangay summary ─────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/billing/compliant/summary");
      if (!res.ok) throw new Error("Failed to load compliance summary.");
      const data: BarangaySummary[] = await res.json();
      setSummary(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Error loading summary.");
    }
  }, []);

  // ── Fetch compliant properties ─────────────────────────────────────────────
  const fetchProperties = useCallback(
    async (reset = true) => {
      setLoadingProps(true);
      setError("");
      try {
        const params = new URLSearchParams({ limit: "50" });
        if (selectedBarangay && selectedBarangay !== "ALL")
          params.set("barangay", selectedBarangay);
        if (!reset && cursor) params.set("cursor", String(cursor));

        const res = await fetch(`/api/v1/billing/compliant?${params}`);
        if (!res.ok) throw new Error("Failed to load compliant properties.");
        const data = await res.json();

        const items: CompliantProperty[] = data.items ?? [];

        // Client-side search filter (name / TDN)
        const filtered = search.trim()
          ? items.filter(
              (p) =>
                p.owner_name.toLowerCase().includes(search.toLowerCase()) ||
                p.td_number.toLowerCase().includes(search.toLowerCase())
            )
          : items;

        setProperties(reset ? filtered : (prev) => [...prev, ...filtered]);
        setHasMore(data.has_more ?? false);
        setCursor(data.next_cursor ?? null);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Error loading properties.");
      } finally {
        setLoadingProps(false);
      }
    },
    [selectedBarangay, cursor, search]
  );

  // Initial load
  useEffect(() => {
    setLoading(true);
    Promise.all([fetchSummary(), fetchProperties(true)]).finally(() =>
      setLoading(false)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-fetch when barangay filter changes
  useEffect(() => {
    setCursor(null);
    fetchProperties(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBarangay]);

  // ── Totals from summary ────────────────────────────────────────────────────
  const totalProperties = summary.reduce((s, r) => s + r.total_properties, 0);
  const totalCompliant = summary.reduce((s, r) => s + r.compliant_count, 0);
  const overallRate =
    totalProperties > 0
      ? ((totalCompliant / totalProperties) * 100).toFixed(1)
      : "0.0";
  const totalCollected = summary.reduce(
    (s, r) => s + r.collected_from_compliant,
    0
  );

  // ── Export CSV ─────────────────────────────────────────────────────────────
  const exportCSV = () => {
    const header = [
      "TD Number",
      "Owner Name",
      "Barangay",
      "Kind",
      "Total Due",
      "Total Paid",
      "Last OR",
      "Last Paid",
      "Years Covered",
    ].join(",");
    const rows = properties.map((p) =>
      [
        p.td_number,
        `"${p.owner_name}"`,
        p.barangay,
        p.kind_of_property,
        p.total_due.toFixed(2),
        p.total_paid.toFixed(2),
        p.last_or ?? "",
        p.last_paid ?? "",
        p.years_covered,
      ].join(",")
    );
    const csv = [header, ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `compliant_properties_${selectedBarangay}_${new Date()
      .toISOString()
      .slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400 text-sm font-bold uppercase tracking-widest">
            Loading compliance data...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* ── Page Header ── */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">
            Revenue Compliance
          </p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">
            Compliant Properties
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Properties with zero outstanding balance across all billing years
          </p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={() => {
              setCursor(null);
              fetchSummary();
              fetchProperties(true);
            }}
            className="flex items-center gap-2 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold text-xs uppercase tracking-wider rounded-xl border border-slate-700 transition-all"
          >
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button
            onClick={exportCSV}
            disabled={properties.length === 0}
            className="flex items-center gap-2 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white font-bold text-xs uppercase tracking-wider rounded-xl transition-all"
          >
            <Download className="w-4 h-4" /> Export CSV
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 text-sm text-red-300 font-bold">
          {error}
        </div>
      )}

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-emerald-500/10 text-emerald-400 rounded-xl flex items-center justify-center">
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">
              Compliant
            </span>
          </div>
          <p className="text-3xl font-black text-white">
            {totalCompliant.toLocaleString()}
          </p>
          <p className="text-xs text-slate-500 mt-1">
            of {totalProperties.toLocaleString()} total properties
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-blue-500/10 text-blue-400 rounded-xl flex items-center justify-center">
              <TrendingUp className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">
              Compliance Rate
            </span>
          </div>
          <p className="text-3xl font-black text-white">{overallRate}%</p>
          <p className="text-xs text-slate-500 mt-1">municipality-wide</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-purple-500/10 text-purple-400 rounded-xl flex items-center justify-center">
              <BarChart3 className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">
              Total Collected
            </span>
          </div>
          <p className="text-2xl font-black text-white">{fmt(totalCollected)}</p>
          <p className="text-xs text-slate-500 mt-1">from compliant properties</p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 bg-orange-500/10 text-orange-400 rounded-xl flex items-center justify-center">
              <Users className="w-5 h-5" />
            </div>
            <span className="text-xs font-bold text-slate-500 uppercase tracking-widest">
              Barangays
            </span>
          </div>
          <p className="text-3xl font-black text-white">{summary.length}</p>
          <p className="text-xs text-slate-500 mt-1">with billing records</p>
        </div>
      </div>

      {/* ── Barangay Summary Table ── */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center gap-3">
          <MapPin className="w-5 h-5 text-[#4ca2ff]" />
          <h2 className="font-black text-sm text-white uppercase tracking-wider">
            Compliance by Barangay
          </h2>
          <span className="text-xs text-slate-500 ml-auto">
            Click a row to filter the property list below
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-950/60 border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider font-extrabold">
                <th className="px-6 py-3 text-left">Barangay</th>
                <th className="px-6 py-3 text-right">Total</th>
                <th className="px-6 py-3 text-right">Compliant</th>
                <th className="px-6 py-3 text-right">Delinquent</th>
                <th className="px-6 py-3 text-center">Rate</th>
                <th className="px-6 py-3 text-right">Collected</th>
                <th className="px-6 py-3 text-center w-10"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {/* ALL row */}
              <tr
                onClick={() => setSelectedBarangay("ALL")}
                className={`cursor-pointer transition-colors hover:bg-slate-800/40 ${
                  selectedBarangay === "ALL" ? "bg-emerald-500/5 border-l-2 border-l-emerald-500" : ""
                }`}
              >
                <td className="px-6 py-3 font-black text-white">ALL BARANGAYS</td>
                <td className="px-6 py-3 text-right font-bold text-slate-300">
                  {totalProperties.toLocaleString()}
                </td>
                <td className="px-6 py-3 text-right font-bold text-emerald-400">
                  {totalCompliant.toLocaleString()}
                </td>
                <td className="px-6 py-3 text-right font-bold text-orange-400">
                  {(totalProperties - totalCompliant).toLocaleString()}
                </td>
                <td className="px-6 py-3 text-center">
                  <RateBadge rate={parseFloat(overallRate)} />
                </td>
                <td className="px-6 py-3 text-right font-bold text-slate-300">
                  {fmt(totalCollected)}
                </td>
                <td className="px-6 py-3 text-center">
                  {selectedBarangay === "ALL" && (
                    <ChevronRight className="w-4 h-4 text-emerald-400 mx-auto" />
                  )}
                </td>
              </tr>

              {summary.map((row) => (
                <tr
                  key={row.barangay}
                  onClick={() => setSelectedBarangay(row.barangay)}
                  className={`cursor-pointer transition-colors hover:bg-slate-800/40 ${
                    selectedBarangay === row.barangay
                      ? "bg-emerald-500/5 border-l-2 border-l-emerald-500"
                      : ""
                  }`}
                >
                  <td className="px-6 py-3 font-bold text-slate-200">
                    {row.barangay}
                  </td>
                  <td className="px-6 py-3 text-right text-slate-400">
                    {row.total_properties.toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-right font-bold text-emerald-400">
                    {row.compliant_count.toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-right text-orange-400">
                    {row.delinquent_count.toLocaleString()}
                  </td>
                  <td className="px-6 py-3 text-center">
                    <RateBadge rate={row.compliance_rate} />
                  </td>
                  <td className="px-6 py-3 text-right text-slate-300">
                    {fmt(row.collected_from_compliant)}
                  </td>
                  <td className="px-6 py-3 text-center">
                    {selectedBarangay === row.barangay && (
                      <ChevronRight className="w-4 h-4 text-emerald-400 mx-auto" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Property List ── */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800 flex flex-col sm:flex-row sm:items-center gap-3">
          <div className="flex items-center gap-3 flex-1">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            <h2 className="font-black text-sm text-white uppercase tracking-wider">
              {selectedBarangay === "ALL"
                ? "All Compliant Properties"
                : `Compliant — ${selectedBarangay}`}
            </h2>
            <span className="text-xs font-bold text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded-full">
              {properties.length} shown
            </span>
          </div>

          {/* Search within results */}
          <div className="relative w-full sm:w-72">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Filter by name or TDN..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-slate-950 border border-slate-800 rounded-xl text-white text-sm placeholder-slate-500 outline-none focus:ring-2 focus:ring-emerald-500/50"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
              >
                <Filter className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-950/60 border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider font-extrabold">
                <th className="px-6 py-3 text-left">TD Number</th>
                <th className="px-6 py-3 text-left">Owner Name</th>
                <th className="px-6 py-3 text-left">Barangay</th>
                <th className="px-6 py-3 text-left">Kind</th>
                <th className="px-6 py-3 text-right">Total Paid</th>
                <th className="px-6 py-3 text-center">Years</th>
                <th className="px-6 py-3 text-left">Last OR</th>
                <th className="px-6 py-3 text-left">Last Paid</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {loadingProps && properties.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center text-slate-500 font-bold">
                    <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                    Loading...
                  </td>
                </tr>
              ) : properties.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center text-slate-500 font-bold">
                    No compliant properties found
                    {selectedBarangay !== "ALL" ? ` in ${selectedBarangay}` : ""}.
                  </td>
                </tr>
              ) : (
                properties.map((p) => (
                  <tr
                    key={p.id}
                    className="hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-6 py-3 font-black text-white">
                      {p.td_number}
                    </td>
                    <td className="px-6 py-3 font-semibold text-slate-200">
                      {p.owner_name}
                    </td>
                    <td className="px-6 py-3 text-slate-400">{p.barangay}</td>
                    <td className="px-6 py-3">
                      <span className="text-[10px] font-extrabold text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded-full uppercase">
                        {p.kind_of_property}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-right font-black text-emerald-400">
                      {fmt(p.total_paid)}
                    </td>
                    <td className="px-6 py-3 text-center">
                      <span className="text-[10px] font-extrabold text-slate-400 bg-slate-800 border border-slate-700 px-2 py-0.5 rounded-full">
                        {p.years_covered} yr{p.years_covered !== 1 ? "s" : ""}
                      </span>
                    </td>
                    <td className="px-6 py-3 text-slate-400 font-mono text-xs">
                      {p.last_or ?? "—"}
                    </td>
                    <td className="px-6 py-3 text-slate-400 text-xs">
                      {p.last_paid ?? "—"}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Load more */}
        {hasMore && (
          <div className="px-6 py-4 border-t border-slate-800 text-center">
            <button
              onClick={() => fetchProperties(false)}
              disabled={loadingProps}
              className="px-6 py-2.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 font-bold text-xs uppercase tracking-wider rounded-xl border border-slate-700 transition-all"
            >
              {loadingProps ? "Loading..." : "Load More"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
