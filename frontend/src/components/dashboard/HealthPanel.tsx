"use client";

import { useEffect, useState } from "react";

interface ServiceStatus {
  ok: boolean;
  latency_ms?: number;
  error?: string;
  version?: string;
  device?: string;
}

interface AIStatus {
  yolo: { ok: boolean; device?: string };
  reid: { ok: boolean };
}

interface HealthData {
  status: "ok" | "degraded" | "down";
  version: string;
  services: {
    database: ServiceStatus;
    redis: ServiceStatus;
    qdrant: ServiceStatus;
    ai: AIStatus;
    cameras: { ok: boolean; total: number; running: number };
  };
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const HEALTH_URL = API_URL.replace("/api/v1", "") + "/health/detail";

const DOT_COLORS = {
  ok: "var(--green)",
  degraded: "var(--yellow)",
  down: "var(--red)",
  unknown: "var(--text-dim)",
};

export function HealthPanel() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetch_() {
      try {
        const res = await fetch(HEALTH_URL);
        const data: HealthData = await res.json();
        setHealth(data);
      } catch {
        setHealth(null);
      } finally {
        setLoading(false);
      }
    }
    fetch_();
    const id = setInterval(fetch_, 10_000);
    return () => clearInterval(id);
  }, []);

  if (loading) {
    return (
      <div className="glass-card-sm p-4 text-xs" style={{ color: "var(--text-dim)" }}>
        Проверка сервисов…
      </div>
    );
  }

  if (!health) {
    return (
      <div className="glass-card-sm p-4 text-xs" style={{ borderColor: "rgba(255,59,92,0.3)", color: "var(--red)" }}>
        Backend недоступен
      </div>
    );
  }

  const rows: { label: string; ok: boolean; detail?: string }[] = [
    {
      label: "PostgreSQL",
      ok: health.services.database.ok,
      detail: health.services.database.latency_ms != null
        ? `${health.services.database.latency_ms}ms`
        : health.services.database.error,
    },
    {
      label: "Redis",
      ok: health.services.redis.ok,
      detail: health.services.redis.latency_ms != null
        ? `${health.services.redis.latency_ms}ms`
        : health.services.redis.error,
    },
    {
      label: "Qdrant",
      ok: health.services.qdrant.ok,
      detail: health.services.qdrant.version ? `v${health.services.qdrant.version}` : health.services.qdrant.error,
    },
    {
      label: "YOLO AI",
      ok: health.services.ai.yolo.ok,
      detail: health.services.ai.yolo.device ?? "—",
    },
    {
      label: "Face ReID",
      ok: health.services.ai.reid.ok,
    },
    {
      label: "Камеры",
      ok: health.services.cameras.ok,
      detail: `${health.services.cameras.running}/${health.services.cameras.total} активны`,
    },
  ];

  const overallColor = DOT_COLORS[health.status] ?? DOT_COLORS.unknown;

  return (
    <div className="glass-card-sm p-4 space-y-2">
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <div
          className="w-2.5 h-2.5 rounded-full"
          style={{ background: overallColor, boxShadow: `0 0 6px ${overallColor}` }}
        />
        <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--text-dim)" }}>
          Состояние системы
        </span>
        <span className="ml-auto text-[10px] font-mono" style={{ color: overallColor }}>
          {health.status.toUpperCase()}
        </span>
      </div>

      {/* Service rows */}
      {rows.map(({ label, ok, detail }) => (
        <div key={label} className="flex items-center gap-2 text-xs">
          <div
            className="w-1.5 h-1.5 rounded-full shrink-0"
            style={{ background: ok ? "var(--green)" : "var(--red)" }}
          />
          <span style={{ color: "var(--text)" }}>{label}</span>
          {detail && (
            <span className="ml-auto font-mono" style={{ color: "var(--text-dim)", fontSize: "10px" }}>
              {detail}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
