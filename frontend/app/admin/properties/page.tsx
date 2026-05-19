"use client";

import { useEffect, useState } from "react";
import { 
  Building2, 
  Search, 
  Plus, 
  Edit3, 
  Trash2, 
  CheckSquare, 
  Square,
  AlertCircle,
  X,
  Sparkles
} from "lucide-react";

export default function AdminProperties() {
  const [query, setQuery] = useState("");
  const [properties, setProperties] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  
  // Modals
  const [showModal, setShowModal] = useState(false);
  const [modalMode, setModalMode] = useState<"create" | "edit">("create");
  const [editingId, setEditingId] = useState<any>(null);
  
  // Form values
  const [tdNumber, setTdNumber] = useState("");
  const [pin, setPin] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [assessedValue, setAssessedValue] = useState("");
  const [barangay, setBarangay] = useState("Poblacion");
  const [kind, setKind] = useState("Residential");
  const [taxYear, setTaxYear] = useState("2024");
  
  // Selection & Bulk Actions
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkBarangay, setBulkBarangay] = useState("Poblacion");
  const [bulkUpdating, setBulkUpdating] = useState(false);

  const fetchProperties = async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("mto_token");
      // GET request with search query
      const url = query 
        ? `/api/v1/properties?search=${encodeURIComponent(query)}`
        : "/api/v1/properties";
      
      const res = await fetch(url, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      
      if (!res.ok) throw new Error("Failed to retrieve property records.");
      const json = await res.json();
      const rawItems = Array.isArray(json) ? json : (json && Array.isArray(json.items) ? json.items : []);
      const mapped = rawItems.map((item: any) => {
        if (Array.isArray(item)) {
          const balance = item[14] || 0;
          return {
            id: item[0],
            td_number: item[1],
            owner_name: item[2],
            payor_name: item[3],
            lot_number: item[4],
            area: item[5],
            location: item[6],
            kind: item[7],
            assessed_value: item[9],
            tax_year: item[17],
            pin: item[18],
            barangay: item[22],
            status: balance > 0 ? "DELINQUENT" : "ACTIVE"
          };
        }
        return item;
      });
      setProperties(mapped);
    } catch (err: any) {
      setError(err.message);
      setProperties([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProperties();
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchProperties();
  };

  const handleCreateOrEditSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    try {
      const token = localStorage.getItem("mto_token");
      const url = modalMode === "create" 
        ? "/api/v1/properties" 
        : `/api/v1/properties/${editingId}`;
      
      const method = modalMode === "create" ? "POST" : "PUT";
      
      const res = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          td_number: tdNumber,
          pin,
          owner_name: ownerName,
          assessed_value: parseFloat(assessedValue),
          barangay,
          kind,
          tax_year: taxYear
        })
      });

      if (!res.ok) throw new Error("Failed to save property registry.");
      
      setShowModal(false);
      fetchProperties();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const openCreateModal = () => {
    setModalMode("create");
    setEditingId(null);
    setTdNumber("");
    setPin("");
    setOwnerName("");
    setAssessedValue("");
    setBarangay("Poblacion");
    setKind("Residential");
    setTaxYear("2024");
    setShowModal(true);
  };

  const openEditModal = (p: any) => {
    setModalMode("edit");
    setEditingId(p.id);
    setTdNumber(p.td_number || "");
    setPin(p.pin || "");
    setOwnerName(p.owner_name || "");
    setAssessedValue(p.assessed_value?.toString() || "");
    setBarangay(p.barangay || "Poblacion");
    setKind(p.kind || "Residential");
    setTaxYear(p.tax_year || "2024");
    setShowModal(true);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Are you sure you want to delete this property assessment?")) return;
    try {
      const token = localStorage.getItem("mto_token");
      const res = await fetch(`/api/v1/properties/${id}`, {
        method: "DELETE",
        headers: { 
          "Authorization": `Bearer ${token}`,
          "X-Requested-With": "XMLHttpRequest"
        }
      });
      if (!res.ok) throw new Error("Failed to delete property registry.");
      fetchProperties();
    } catch (err: any) {
      setError(err.message);
    }
  };

  // Selectors
  const toggleSelect = (id: number) => {
    setSelectedIds(prev => 
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  const toggleSelectAll = () => {
    if (selectedIds.length === properties.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(properties.map(p => p.id));
    }
  };

  // Bulk update
  const handleBulkUpdate = async () => {
    if (selectedIds.length === 0) return;
    setBulkUpdating(true);
    setError("");
    try {
      const token = localStorage.getItem("mto_token");
      const res = await fetch("/api/v1/properties/bulk-update-barangay", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`,
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify({
          ids: selectedIds,
          barangay: bulkBarangay
        })
      });

      if (!res.ok) throw new Error("Bulk updates failed.");
      setSelectedIds([]);
      fetchProperties();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBulkUpdating(false);
    }
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Header section */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Real Property Unit</p>
          <h1 className="text-3xl font-black text-white tracking-tight uppercase mt-0.5">Property Registry</h1>
        </div>
        <button
          onClick={openCreateModal}
          className="flex items-center justify-center gap-2 px-5 py-3 bg-[#1f4e78] hover:bg-[#2c6ea1] text-white font-bold text-sm uppercase tracking-wider rounded-xl transition-all shadow-lg shadow-[#1f4e78]/25"
        >
          <Plus className="w-5 h-5" /> Register Property
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/25 rounded-2xl p-4 flex gap-3 text-sm text-red-300">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <span className="font-bold flex-1">{error}</span>
        </div>
      )}

      {/* Search Bar Panel */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <form onSubmit={handleSearchSubmit} className="flex gap-3">
          <div className="relative flex-1">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-500">
              <Search className="w-5 h-5" />
            </span>
            <input
              type="text"
              className="w-full pl-10 pr-4 py-3 bg-slate-950 border border-slate-800 rounded-xl text-white placeholder-slate-500 focus:ring-2 focus:ring-[#1f4e78] focus:border-transparent outline-none transition-all text-sm"
              placeholder="Search TD Number, PIN, or Owner Name..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="bg-slate-800 hover:bg-slate-750 text-slate-200 px-6 py-3 rounded-xl font-bold text-xs uppercase tracking-wider border border-slate-750 transition-all disabled:opacity-50"
          >
            {loading ? "SEARCHING..." : "QUERY"}
          </button>
        </form>
      </div>

      {/* Main Table Screen */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-xl shadow-black/15">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="bg-slate-950/60 border-b border-slate-800 text-slate-400 font-extrabold text-xs uppercase tracking-wider">
                <th className="px-6 py-4 w-12 text-center">
                  <button onClick={toggleSelectAll} className="text-slate-400 hover:text-white">
                    {selectedIds.length === properties.length && properties.length > 0 ? (
                      <CheckSquare className="w-5 h-5 text-[#4ca2ff]" />
                    ) : (
                      <Square className="w-5 h-5" />
                    )}
                  </button>
                </th>
                <th className="px-6 py-4 font-extrabold">TD Number</th>
                <th className="px-6 py-4 font-extrabold">Owner</th>
                <th className="px-6 py-4 font-extrabold">Barangay</th>
                <th className="px-6 py-4 font-extrabold">Kind</th>
                <th className="px-6 py-4 font-extrabold text-right">Assessed Value</th>
                <th className="px-6 py-4 font-extrabold text-center">Status</th>
                <th className="px-6 py-4 font-extrabold text-center w-28">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {properties.length > 0 ? (
                properties.map((p, i) => {
                  const isSelected = selectedIds.includes(p.id);
                  const isDelinquent = p.status === "DELINQUENT";
                  return (
                    <tr key={i} className={`hover:bg-slate-850/40 transition-colors ${isSelected ? 'bg-[#1f4e78]/5' : ''}`}>
                      <td className="px-6 py-4 text-center">
                        <button onClick={() => toggleSelect(p.id)} className="text-slate-400 hover:text-white">
                          {isSelected ? (
                            <CheckSquare className="w-5 h-5 text-[#4ca2ff]" />
                          ) : (
                            <Square className="w-5 h-5" />
                          )}
                        </button>
                      </td>
                      <td className="px-6 py-4 font-bold text-white">{p.td_number}</td>
                      <td className="px-6 py-4 text-slate-300 font-semibold">{p.owner_name}</td>
                      <td className="px-6 py-4 text-slate-400">{p.barangay}</td>
                      <td className="px-6 py-4">
                        <span className="text-[10px] font-extrabold text-blue-400 bg-blue-500/10 border border-blue-500/20 px-2 py-0.5 rounded-full uppercase">
                          {p.kind}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-right font-black text-slate-200">P {p.assessed_value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                      <td className="px-6 py-4 text-center">
                        <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full uppercase border ${
                          isDelinquent 
                            ? 'text-orange-400 bg-orange-500/10 border-orange-500/20' 
                            : 'text-green-400 bg-green-500/10 border-green-500/20'
                        }`}>
                          {p.status}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-center">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            onClick={() => openEditModal(p)}
                            className="p-1.5 bg-slate-800 hover:bg-slate-750 text-slate-300 rounded-lg border border-slate-700 transition-colors"
                          >
                            <Edit3 className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(p.id)}
                            className="p-1.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-lg border border-red-500/20 transition-colors"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={8} className="py-20 text-center text-slate-500 font-bold">
                    No matching property assessments found in the registry.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Bulk Barangay Actions Drawer at Bottom */}
      {selectedIds.length > 0 && (
        <div className="bg-slate-900 border border-[#1f4e78]/40 shadow-2xl rounded-2xl p-6 flex flex-col md:flex-row items-center justify-between gap-4 animate-slide-up border-b-4 border-b-[#1f4e78]">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#1f4e78]/25 text-[#4ca2ff] rounded-xl flex items-center justify-center">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <p className="font-extrabold text-sm text-white">{selectedIds.length} Properties Selected</p>
              <p className="text-[10px] text-slate-500 uppercase tracking-widest">Execute bulk maintenance action</p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-3 w-full md:w-auto">
            <select
              className="w-full sm:w-48 bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
              value={bulkBarangay}
              onChange={(e) => setBulkBarangay(e.target.value)}
            >
              <option value="Poblacion">Poblacion</option>
              <option value="San Jose">San Jose</option>
              <option value="Santo Tomas">Santo Tomas</option>
              <option value="Santa Cruz">Santa Cruz</option>
              <option value="San Vicente">San Vicente</option>
            </select>
            <button
              onClick={handleBulkUpdate}
              disabled={bulkUpdating}
              className="w-full sm:w-auto bg-[#1f4e78] hover:bg-[#2c6ea1] disabled:opacity-50 text-white font-bold text-xs uppercase tracking-widest px-6 py-3 rounded-xl transition-all whitespace-nowrap"
            >
              {bulkUpdating ? "UPDATING..." : "UPDATE BARANGAY"}
            </button>
          </div>
        </div>
      )}

      {/* Create / Edit Modal Form Overlay */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-xl w-full bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden animate-zoom-in">
            <div className="px-6 py-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
              <h3 className="font-bold text-base text-white uppercase tracking-wider flex items-center gap-2">
                <Building2 className="w-5 h-5 text-[#4ca2ff]" />
                {modalMode === "create" ? "Register New Assessment" : "Modify Property Assessment"}
              </h3>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-6 h-6" />
              </button>
            </div>

            <form onSubmit={handleCreateOrEditSubmit} className="p-6 space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">TD Number</label>
                  <input
                    type="text"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                    placeholder="e.g. TD-2023-001"
                    value={tdNumber}
                    onChange={(e) => setTdNumber(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">PIN</label>
                  <input
                    type="text"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                    placeholder="e.g. PIN-001"
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Owner Name</label>
                <input
                  type="text"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                  placeholder="Full owner name"
                  value={ownerName}
                  onChange={(e) => setOwnerName(e.target.value)}
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Assessed Value (P)</label>
                  <input
                    type="number"
                    step="0.01"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                    placeholder="0.00"
                    value={assessedValue}
                    onChange={(e) => setAssessedValue(e.target.value)}
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Barangay</label>
                  <select
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                    value={barangay}
                    onChange={(e) => setBarangay(e.target.value)}
                  >
                    <option value="Poblacion">Poblacion</option>
                    <option value="San Jose">San Jose</option>
                    <option value="Santo Tomas">Santo Tomas</option>
                    <option value="Santa Cruz">Santa Cruz</option>
                    <option value="San Vicente">San Vicente</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 col-span-2">
                <div>
                  <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Property Kind</label>
                  <select
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                    value={kind}
                    onChange={(e) => setKind(e.target.value)}
                  >
                    <option value="Residential">Residential</option>
                    <option value="Commercial">Commercial</option>
                    <option value="Industrial">Industrial</option>
                    <option value="Agricultural">Agricultural</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">Tax Year</label>
                  <input
                    type="text"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]"
                    value={taxYear}
                    onChange={(e) => setTaxYear(e.target.value)}
                    required
                  />
                </div>
              </div>

              <div className="pt-4 border-t border-slate-800 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="bg-slate-800 hover:bg-slate-750 text-slate-350 px-5 py-3 rounded-xl font-bold text-xs uppercase tracking-wider border border-slate-750 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="bg-[#1f4e78] hover:bg-[#2c6ea1] text-white px-6 py-3 rounded-xl font-bold text-xs uppercase tracking-wider transition-colors"
                >
                  {modalMode === "create" ? "Save Assessment" : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
