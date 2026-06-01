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
  Sparkles,
  Info
} from "lucide-react";

// Shared input styling for the property form
const inputCls = "w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm outline-none focus:ring-2 focus:ring-[#1f4e78]";

// Labelled field wrapper for the property form
function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-extrabold uppercase tracking-wider text-slate-500 mb-2">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}

export default function AdminProperties() {
  const [query, setQuery] = useState("");
  const [properties, setProperties] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  
  // Modals
  const [showModal, setShowModal] = useState(false);
  const [modalMode, setModalMode] = useState<"create" | "edit">("create");
  const [editingId, setEditingId] = useState<any>(null);
  const [saving, setSaving] = useState(false);

  // Full property form — mirrors PropertySaveSchema (snake_case accepted by the API)
  const EMPTY_FORM = {
    td_number: "",
    pin: "",
    prev_td_number: "",
    owner_name: "",
    payor_name: "",
    lot_number: "",
    block_number: "",
    area: "",
    location: "",
    barangay: "Poblacion",
    kind_of_property: "Residential",
    accountable_officer: "",
    assessed_value: "",
    penalty: "0",
    discount: "0",
    tax_year: "2024",
    effectivity_date: "",
    version: 0,
  };
  const [form, setForm] = useState<any>({ ...EMPTY_FORM });
  const setField = (k: string, v: any) => setForm((f: any) => ({ ...f, [k]: v }));

  // Selection & Bulk Actions
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [bulkBarangay, setBulkBarangay] = useState("Poblacion");
  const [bulkUpdating, setBulkUpdating] = useState(false);

  const fetchProperties = async () => {
    setLoading(true);
    setError("");
    try {
      const url = query 
        ? `/api/v1/properties?search=${encodeURIComponent(query)}`
        : "/api/v1/properties";
      
      const res = await fetch(url, {
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" }
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
    setSaving(true);
    try {
      const url = modalMode === "create" 
        ? "/api/v1/properties" 
        : `/api/v1/properties/${editingId}`;
      
      const method = modalMode === "create" ? "POST" : "PUT";

      // Build payload from the full form. Empty strings are sent as-is;
      // the backend coerces numerics and treats blanks as null/zero.
      const payload: any = {
        td_number: form.td_number,
        pin: form.pin,
        prev_td_number: form.prev_td_number,
        owner_name: form.owner_name,
        payor_name: form.payor_name,
        lot_number: form.lot_number,
        block_number: form.block_number,
        area: form.area,
        location: form.location,
        barangay: form.barangay,
        kind_of_property: form.kind_of_property,
        accountable_officer: form.accountable_officer,
        assessed_value: form.assessed_value === "" ? 0 : parseFloat(form.assessed_value),
        penalty: form.penalty === "" ? 0 : parseFloat(form.penalty),
        discount: form.discount === "" ? 0 : parseFloat(form.discount),
        tax_year: form.tax_year,
        effectivity_date: form.effectivity_date,
      };
      // Send version only on edit so the backend can detect sync conflicts
      if (modalMode === "edit") payload.version = form.version ?? 0;

      const res = await fetch(url, {
        method,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest"
        },
        body: JSON.stringify(payload)
      });

      if (res.status === 409) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "This record changed since you opened it. Reload and try again.");
      }
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "Failed to save property registry.");
      }
      
      setShowModal(false);
      fetchProperties();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const openCreateModal = () => {
    setModalMode("create");
    setEditingId(null);
    setForm({ ...EMPTY_FORM });
    setError("");
    setShowModal(true);
  };

  const openEditModal = async (p: any) => {
    setModalMode("edit");
    setEditingId(p.id);
    setError("");
    // Pull the full record so every field is editable (the list row is partial)
    try {
      const res = await fetch(`/api/v1/properties/${p.id}`, {
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (res.ok) {
        const full = await res.json();
        setForm({
          td_number: full.td_number ?? "",
          pin: full.pin ?? "",
          prev_td_number: full.prev_td_number ?? "",
          owner_name: full.owner_name ?? "",
          payor_name: full.payor_name ?? "",
          lot_number: full.lot_number ?? "",
          block_number: full.block_number ?? "",
          area: full.area ?? "",
          location: full.location ?? "",
          barangay: full.barangay ?? "Poblacion",
          kind_of_property: full.kind_of_property ?? "Residential",
          accountable_officer: full.accountable_officer ?? "",
          assessed_value: full.assessed_value?.toString() ?? "",
          penalty: full.penalty?.toString() ?? "0",
          discount: full.discount?.toString() ?? "0",
          tax_year: full.tax_year ?? "2024",
          effectivity_date: full.effectivity_date ?? "",
          version: full.version ?? 0,
        });
      } else {
        // Fall back to the partial row data if the detail fetch fails
        setForm({
          ...EMPTY_FORM,
          td_number: p.td_number || "",
          pin: p.pin || "",
          owner_name: p.owner_name || "",
          assessed_value: p.assessed_value?.toString() || "",
          barangay: p.barangay || "Poblacion",
          kind_of_property: p.kind || "Residential",
          tax_year: p.tax_year || "2024",
        });
      }
    } catch {
      setForm({ ...EMPTY_FORM, td_number: p.td_number || "" });
    }
    setShowModal(true);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Are you sure you want to delete this property assessment?")) return;
    try {
      const res = await fetch(`/api/v1/properties/${id}`, {
        method: "DELETE",
        credentials: "include",
        headers: { "X-Requested-With": "XMLHttpRequest" }
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
      const res = await fetch("/api/v1/properties/bulk-update-barangay", {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
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
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-auto shadow-xl shadow-black/15" style={{maxHeight:"calc(100vh - 340px)"}}>
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-slate-950/95 border-b border-slate-800 text-slate-400 font-extrabold text-xs uppercase tracking-wider backdrop-blur">
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
          <div className="max-w-3xl w-full bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden animate-zoom-in max-h-[92vh] flex flex-col">
            <div className="px-6 py-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between flex-shrink-0">
              <h3 className="font-bold text-base text-white uppercase tracking-wider flex items-center gap-2">
                <Building2 className="w-5 h-5 text-[#4ca2ff]" />
                {modalMode === "create" ? "Register New Assessment" : "Modify Property Assessment"}
              </h3>
              <button onClick={() => setShowModal(false)} className="text-slate-400 hover:text-white">
                <X className="w-6 h-6" />
              </button>
            </div>

            <form onSubmit={handleCreateOrEditSubmit} className="p-6 space-y-6 overflow-y-auto">
              {/* ── Identification ── */}
              <div>
                <p className="text-[11px] font-black text-[#4ca2ff] uppercase tracking-widest mb-3">Identification</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <Field label="TD Number" required>
                    <input className={inputCls} placeholder="e.g. 06-0012-01379"
                      value={form.td_number} onChange={(e) => setField("td_number", e.target.value)} required />
                  </Field>
                  <Field label="PIN">
                    <input className={inputCls} placeholder="e.g. 123-45-678-00-001"
                      value={form.pin} onChange={(e) => setField("pin", e.target.value)} />
                  </Field>
                  <Field label="Previous TD Number">
                    <input className={inputCls} placeholder="Prior TDN (if reissued)"
                      value={form.prev_td_number} onChange={(e) => setField("prev_td_number", e.target.value)} />
                  </Field>
                </div>
              </div>

              {/* ── Ownership ── */}
              <div>
                <p className="text-[11px] font-black text-[#4ca2ff] uppercase tracking-widest mb-3">Ownership</p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <Field label="Owner Name" required>
                    <input className={inputCls} placeholder="Registered owner"
                      value={form.owner_name} onChange={(e) => setField("owner_name", e.target.value)} required />
                  </Field>
                  <Field label="Payor">
                    <input className={inputCls} placeholder="Defaults to owner if blank"
                      value={form.payor_name} onChange={(e) => setField("payor_name", e.target.value)} />
                  </Field>
                  <Field label="Accountable Officer">
                    <input className={inputCls} placeholder="Assessing/collecting officer"
                      value={form.accountable_officer} onChange={(e) => setField("accountable_officer", e.target.value)} />
                  </Field>
                </div>
              </div>

              {/* ── Location ── */}
              <div>
                <p className="text-[11px] font-black text-[#4ca2ff] uppercase tracking-widest mb-3">Location &amp; Land</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <Field label="Lot Number">
                    <input className={inputCls} value={form.lot_number} onChange={(e) => setField("lot_number", e.target.value)} />
                  </Field>
                  <Field label="Block Number">
                    <input className={inputCls} value={form.block_number} onChange={(e) => setField("block_number", e.target.value)} />
                  </Field>
                  <Field label="Area">
                    <input className={inputCls} placeholder="e.g. 250 sqm" value={form.area} onChange={(e) => setField("area", e.target.value)} />
                  </Field>
                  <Field label="Location">
                    <input className={inputCls} placeholder="Street / sitio" value={form.location} onChange={(e) => setField("location", e.target.value)} />
                  </Field>
                  <Field label="Barangay">
                    <select className={inputCls} value={form.barangay} onChange={(e) => setField("barangay", e.target.value)}>
                      <option value="Poblacion">Poblacion</option>
                      <option value="San Jose">San Jose</option>
                      <option value="Santo Tomas">Santo Tomas</option>
                      <option value="Santa Cruz">Santa Cruz</option>
                      <option value="San Vicente">San Vicente</option>
                    </select>
                  </Field>
                  <Field label="Property Kind">
                    <select className={inputCls} value={form.kind_of_property} onChange={(e) => setField("kind_of_property", e.target.value)}>
                      <option value="Residential">Residential</option>
                      <option value="Commercial">Commercial</option>
                      <option value="Industrial">Industrial</option>
                      <option value="Agricultural">Agricultural</option>
                    </select>
                  </Field>
                </div>
              </div>

              {/* ── Assessment & Tax ── */}
              <div>
                <p className="text-[11px] font-black text-[#4ca2ff] uppercase tracking-widest mb-3">Assessment &amp; Tax</p>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  <Field label="Assessed Value (₱)" required>
                    <input type="number" step="0.01" className={inputCls} placeholder="0.00"
                      value={form.assessed_value} onChange={(e) => setField("assessed_value", e.target.value)} required />
                  </Field>
                  <Field label="Tax Year(s)" required>
                    <input className={inputCls} placeholder="2024 or 2022-2024"
                      value={form.tax_year} onChange={(e) => setField("tax_year", e.target.value)} required />
                  </Field>
                  <Field label="Effectivity Date">
                    <input type="date" className={inputCls}
                      value={form.effectivity_date} onChange={(e) => setField("effectivity_date", e.target.value)} />
                  </Field>
                  <Field label="Penalty (₱)">
                    <input type="number" step="0.01" className={inputCls}
                      value={form.penalty} onChange={(e) => setField("penalty", e.target.value)} />
                  </Field>
                  <Field label="Discount (₱)">
                    <input type="number" step="0.01" className={inputCls}
                      value={form.discount} onChange={(e) => setField("discount", e.target.value)} />
                  </Field>
                </div>
              </div>

              {/* ── Posting note ── */}
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 flex items-start gap-3">
                <Info className="w-4 h-4 text-[#4ca2ff] flex-shrink-0 mt-0.5" />
                <p className="text-xs text-slate-400 leading-relaxed">
                  This form manages the property <span className="text-slate-300 font-semibold">assessment record only</span>.
                  To post a payment and issue an Official Receipt, use the Cashier
                  workstation (desktop app).
                </p>
              </div>

              <div className="pt-4 border-t border-slate-800 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="bg-slate-800 hover:bg-slate-700 text-slate-300 px-5 py-3 rounded-xl font-bold text-xs uppercase tracking-wider border border-slate-700 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="bg-[#1f4e78] hover:bg-[#2c6ea1] disabled:opacity-50 text-white px-6 py-3 rounded-xl font-bold text-xs uppercase tracking-wider transition-colors"
                >
                  {saving ? "Saving…" : modalMode === "create" ? "Save Assessment" : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
