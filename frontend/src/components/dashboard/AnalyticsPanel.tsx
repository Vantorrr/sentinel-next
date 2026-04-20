"use client";

import { useEffect, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { analyticsApi, type OccupancyPoint } from "@/lib/api";
import { format } from "date-fns";

export function AnalyticsPanel() {
  const today = format(new Date(), "yyyy-MM-dd");
  const [occupancy, setOccupancy] = useState<OccupancyPoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    analyticsApi
      .occupancy(today)
      .then(setOccupancy)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [today]);

  const chartData = occupancy.map((o) => ({
    hour: new Date(o.hour).getHours() + ":00",
    visits: o.visits,
  }));

  return (
    <div className="space-y-4 lg:space-y-6">
      <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--text-dim)" }}>
        Аналитика посещаемости
      </span>

      <div className="glass-card p-4 lg:p-5">
        <p className="text-sm mb-4 font-medium">Посещения по часам — сегодня</p>
        {loading ? (
          <div className="space-y-3">
            <div className="skeleton h-48 w-full" />
            <div className="flex gap-2">
              <div className="skeleton h-4 w-16" />
              <div className="skeleton h-4 w-24" />
              <div className="skeleton h-4 w-12" />
            </div>
          </div>
        ) : chartData.length === 0 ? (
          <div className="h-48 flex items-center justify-center text-xs" style={{ color: "var(--text-dim)" }}>
            Нет данных за сегодня
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#00e5ff" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#00e5ff" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e2738" />
              <XAxis dataKey="hour" tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{
                  background: "rgba(13,17,23,0.9)",
                  border: "1px solid var(--glass-border)",
                  borderRadius: 12,
                  backdropFilter: "blur(8px)",
                }}
                labelStyle={{ color: "#e2e8f0" }}
                itemStyle={{ color: "#00e5ff" }}
              />
              <Area
                type="monotone"
                dataKey="visits"
                stroke="#00e5ff"
                strokeWidth={2}
                fill="url(#areaGrad)"
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          { label: "Средний визит", value: "—", unit: "мин" },
          { label: "Повторные", value: "—", unit: "%" },
          { label: "VIP визиты", value: "—", unit: "сегодня" },
        ].map(({ label, value, unit }) => (
          <div key={label} className="glass-card p-4">
            <p className="text-xs mb-2" style={{ color: "var(--text-dim)" }}>
              {label}
            </p>
            <p className="text-2xl font-bold font-mono" style={{ color: "var(--accent)" }}>
              {value}
              <span className="text-sm ml-1" style={{ color: "var(--text-dim)" }}>
                {unit}
              </span>
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
