"use client";

import { useEffect, useRef, useState } from "react";
import { useSentinelStore } from "@/lib/store";
import { analyticsApi } from "@/lib/api";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { BookOpen, Brain, Camera, Shield, ShieldAlert, TrendingUp, Users } from "lucide-react";

export function OverviewPanel() {
  const cameras = useSentinelStore((s) => s.cameras);
  const occupancy = useSentinelStore((s) => s.occupancyCurrent);
  const latestSummary = useSentinelStore((s) => s.latestSummary);
  const events = useSentinelStore((s) => s.events);
  const unreadAlerts = useSentinelStore((s) => s.unreadAlerts);
  const [rbScore, setRbScore] = useState<number | null>(null);
  const [rbTotal, setRbTotal] = useState(0);

  const activeCams = cameras.filter((c) => c.running).length;

  useEffect(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    analyticsApi
      .redbookRemarks(start.toISOString())
      .then((r) => {
        setRbScore(r.score);
        setRbTotal(r.total);
      })
      .catch(() => {
        setRbScore(null);
      });
  }, [unreadAlerts, events.length]);

  const moodColor = {
    позитивное: "var(--green)",
    нейтральное: "var(--accent)",
    напряжённое: "var(--red)",
  }[latestSummary?.mood ?? "нейтральное"] ?? "var(--accent)";

  return (
    <div className="space-y-3 lg:space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 lg:gap-3">
        <KpiCard icon={<Users size={17} />} label="В зале" value={occupancy} accent="var(--accent)" delay={0} />
        <KpiCard
          icon={<Camera size={17} />}
          label="Камер онлайн"
          value={activeCams}
          suffix={`/${cameras.length}`}
          accent="var(--green)"
          delay={40}
        />
        <KpiCard icon={<TrendingUp size={17} />} label="Событий" value={events.length} accent="var(--ai)" delay={80} />
        <KpiCard
          icon={<ShieldAlert size={17} />}
          label="Замечания"
          value={unreadAlerts}
          accent={unreadAlerts > 0 ? "var(--red)" : "var(--text-dim)"}
          delay={120}
        />
      </div>

      {rbScore !== null && (
        <div className="glass-card p-4 flex items-center gap-4 panel-enter">
          <div
            className="w-11 h-11 rounded-2xl flex items-center justify-center shrink-0"
            style={{ background: "rgba(94,234,212,0.12)", color: "var(--ai)" }}
          >
            <BookOpen size={20} />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] font-mono uppercase tracking-[0.14em]" style={{ color: "var(--text-dim)" }}>
              Красная книга · сегодня
            </p>
            <p className="text-sm mt-0.5" style={{ color: "var(--text)" }}>
              Соответствие стандарту: <span className="font-bold font-mono" style={{ color: rbScore >= 85 ? "var(--green)" : rbScore >= 60 ? "var(--yellow)" : "var(--red)" }}>{rbScore}%</span>
              {rbTotal > 0 ? ` · замечаний: ${rbTotal}` : " · замечаний нет"}
            </p>
          </div>
        </div>
      )}

      {latestSummary && (
        <div className="glass-card p-5 relative overflow-hidden panel-enter">
          <div
            className="absolute -right-8 -top-8 w-40 h-40 rounded-full opacity-[0.12] pointer-events-none"
            style={{ background: "radial-gradient(circle, var(--ai), transparent 70%)" }}
          />

          <div className="flex items-center gap-2 mb-3 relative">
            <Brain size={16} style={{ color: "var(--ai)" }} />
            <span className="text-[11px] font-mono uppercase tracking-[0.16em]" style={{ color: "var(--ai)" }}>
              AI Нарратив
            </span>
            <span className="ml-auto text-xs font-mono" style={{ color: "var(--text-dim)" }}>
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
            <span className="text-xs" style={{ color: "var(--text-dim)" }}>Настроение:</span>
            <span className="text-xs font-semibold" style={{ color: moodColor }}>
              {latestSummary.mood}
            </span>

            {latestSummary.insights.length > 0 && (
              <>
                <span className="text-xs" style={{ color: "var(--text-dim)" }}>Инсайты:</span>
                <span className="text-xs" style={{ color: "var(--accent)" }}>
                  {latestSummary.insights[0]}
                </span>
              </>
            )}
          </div>

          {latestSummary.alerts.length > 0 && (
            <div
              className="mt-3 px-3 py-2.5 rounded-xl text-xs flex items-center gap-2"
              style={{
                background: "rgba(251,113,133,0.08)",
                border: "1px solid rgba(251,113,133,0.2)",
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
  delay = 0,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  suffix?: string;
  accent: string;
  delay?: number;
}) {
  return (
    <div
      className="glass-card p-4 flex flex-col gap-2.5 relative overflow-hidden"
      style={{ animation: `rise-in 0.4s ease-out ${delay}ms both` }}
    >
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-r-full"
        style={{ background: accent }}
      />
      <div className="flex items-center gap-2" style={{ color: accent }}>
        {icon}
        <span className="text-[10px] font-mono uppercase tracking-[0.12em]" style={{ color: "var(--text-dim)" }}>
          {label}
        </span>
      </div>
      <div className="text-3xl font-bold font-mono tracking-tight" style={{ color: accent }}>
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

    const duration = 420;
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
