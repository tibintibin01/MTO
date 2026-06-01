"use client";

import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Cell,
} from "recharts";
import { TrendingUp } from "lucide-react";

interface TrendPoint {
  month: string;
  total: number;
}

const peso = (n: number) =>
  "₱" + (n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Compact peso for axis ticks (e.g. ₱12k, ₱1.2M)
function pesoCompact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `₱${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `₱${(n / 1_000).toFixed(0)}k`;
  return `₱${n}`;
}

function CustomTooltip({ active, payload, label }: any) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs font-bold text-slate-300 uppercase tracking-wider">{label}</p>
      <p className="text-sm font-black text-emerald-400">{peso(payload[0].value)}</p>
    </div>
  );
}

/**
 * Monthly revenue trend chart.
 * Renders an explicit empty state when there is no data so the dashboard
 * never shows a broken/empty chart frame.
 */
export function RevenueTrendChart({ data }: { data: TrendPoint[] }) {
  if (!data || data.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center py-10">
        <TrendingUp className="w-10 h-10 text-slate-700 mb-3" />
        <p className="text-slate-500 text-sm font-bold">No revenue data yet</p>
        <p className="text-slate-600 text-xs mt-1">
          Monthly collections will appear here once payments are posted.
        </p>
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 4 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
        <XAxis
          dataKey="month"
          tick={{ fill: "#64748b", fontSize: 11, fontWeight: 700 }}
          axisLine={{ stroke: "#1e293b" }}
          tickLine={false}
        />
        <YAxis
          tickFormatter={pesoCompact}
          tick={{ fill: "#64748b", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={56}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey="total" radius={[4, 4, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill="#10b981" />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
