"use client";

import { useEffect, useRef } from "react";
import { useSentinelStore } from "@/lib/store";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { Brain, Camera, Shield, ShieldAlert, TrendingUp, Users } from "lucide-react";

export function OverviewPanel() {
  const cameras = useSentinelStore((s) => s.cameras);
  const occupancy = useSentinelStore((s) => s.occupancyCurrent);
  const latestSummary = useSentinelStore((s) => s.latestSummary);
  const events = useSentinelStore((s) => s.events);
  const unreadAlerts = useSentinelStore((s) => s.unreadAlerts);

  const activeCams = cameras.filter((c) => c.running).length;

  const moodColor = {
    позитивное: "var(--green)",
    нейтральное: "var(--accent)",
    напряжённое: "var(--red)",
  }[latestSummary?.mood ?? "нейтральное"] ?? "var(--accent)";

  return (
    <div className="space-y-3 lg:space-y-4">
      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 lg:gap-3">
        <KpiCard
          icon={<Users size={18} />}
          label="В зале"
          value={occupancy}
          accent="var(--accent)"
        />
        <KpiCard
          icon={<Camera size={18} />}
          label="Камер онлайн"
          value={activeCams}
          suffix={`/${cameras.length}`}
          accent="var(--green)"
        />
        <KpiCard
          icon={<TrendingUp size={18} />}
          label="Событий"
          value={events.length}
          accent="#a78bfa"
        />
        <KpiCard
          icon={<ShieldAlert size={18} />}
          label="Алерты"
          value={unreadAlerts}
          accent={unreadAlerts > 0 ? "var(--red)" : "var(--text-dim)"}
        />
      </div>

      {/* Latest LLM Summary */}
      {latestSummary && (
        <div className="glass-card p-5 relative overflow-hidden">
          <div
            className="absolute inset-0 opacity-[0.03] pointer-events-none"
            style={{
              background: "linear-gradient(135deg, var(--accent-2), transparent 60%)",
            }}
          />

          <div className="flex items-center gap-2 mb-3 relative">
            <Brain size={16} style={{ color: "#a78bfa" }} />
            <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "#a78bfa" }}>
              AI Нарратив
            </span>
            <span
              className="ml-auto text-xs font-mono"
              style={{ color: "var(--text-dim)" }}
            >
              {formatDistanceToNow(new Date(latestSummary.timestamp_ms), {
                addSuffix: true,
                locale: ru,
              })}
            </span>
          </div>

          <p className="text-sm leading-relaxed relative" style={{ color: "var(--text)" }}>
            {latestSummary.narrative}
          </p>

          <div className="flex items-center gap-4 mt-4 flex-wrap relative">
            <span className="text-xs" style={{ color: "var(--text-dim)" }}>
              Настроение:
            </span>
            <span className="text-xs font-semibold" style={{ color: moodColor }}>
              {latestSummary.mood}
            </span>

            {latestSummary.insights.length > 0 && (
              <>
                <span className="text-xs" style={{ color: "var(--text-dim)" }}>
                  Инсайты:
                </span>
                <span className="text-xs" style={{ color: "var(--accent)" }}>
                  {latestSummary.insights[0]}
                </span>
              </>
            )}
          </div>

          {latestSummary.alerts.length > 0 && (
            <div
              className="mt-3 px-3 py-2 rounded-xl text-xs flex items-center gap-2"
              style={{
                background: "rgba(255,59,92,0.08)",
                border: "1px solid rgba(255,59,92,0.2)",
                color: "var(--red)",
              }}
            >
              <Shield size={12} className="shrink-0" />
              {latestSummary.alerts.join(" · ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function KpiCard({
  icon,
  label,
  value,
  suffix,
  accent,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  suffix?: string;
  accent: string;
}) {
  return (
    <div className="glass-card p-4 flex flex-col gap-2 relative overflow-hidden">
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-r-full"
        style={{ background: accent }}
      />
      <div className="flex items-center gap-2" style={{ color: accent }}>
        {icon}
        <span className="text-[11px] font-mono uppercase tracking-wider" style={{ color: "var(--text-dim)" }}>
          {label}
        </span>
      </div>
      <div className="text-3xl font-bold font-mono" style={{ color: accent }}>
        <AnimatedNumber value={value} />
        {suffix && <span className="text-lg ml-0.5" style={{ color: "var(--text-dim)" }}>{suffix}</span>}
      </div>
    </div>
  );
}

function AnimatedNumber({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prevRef = useRef(value);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const from = prevRef.current;
    const to = value;
    prevRef.current = value;

    if (from === to) {
      el.textContent = String(to);
      return;
    }

    const duration = 400;
    const start = performance.now();

    function tick(now: number) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(from + (to - from) * eased);
      if (el) el.textContent = String(current);
      if (progress < 1) requestAnimationFrame(tick);
    }

    requestAnimationFrame(tick);
  }, [value]);

  return <span ref={ref}>{value}</span>;
}
