"use client";

import {
  Activity,
  Bot,
  Camera,
  LayoutDashboard,
  Map,
  MapPin,
  Settings,
  ShieldAlert,
  Users,
} from "lucide-react";
import type { Tab } from "./DashboardShell";
import { useSentinelStore } from "@/lib/store";
import { HealthPanel } from "./HealthPanel";

interface Props {
  activeTab: Tab;
  onTabChange: (t: Tab) => void;
  onChatToggle: () => void;
  showAdmin?: boolean;
}

const NAV: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "cameras", label: "Камеры", icon: Camera },
  { id: "zones", label: "Зоны", icon: MapPin },
  { id: "heatmap", label: "Карта", icon: Map },
  { id: "analytics", label: "Аналитика", icon: Activity },
  { id: "persons", label: "Люди", icon: Users },
];

export function Sidebar({ activeTab, onTabChange, onChatToggle, showAdmin }: Props) {
  const unreadAlerts = useSentinelStore((s) => s.unreadAlerts);
  const clearAlerts = useSentinelStore((s) => s.clearAlerts);
  const occupancy = useSentinelStore((s) => s.occupancyCurrent);

  const tabs = showAdmin
    ? [...NAV, { id: "admin" as Tab, label: "Админ", icon: Settings }]
    : NAV;

  return (
    <>
      {/* ── Desktop sidebar (lg+) ──────────────────────────────── */}
      <aside className="hidden lg:flex w-60 flex-col py-4 border-r shrink-0 glass-surface">
        {/* Logo */}
        <div className="px-4 mb-6 flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 glow-cyan"
            style={{ background: "var(--accent)" }}
          >
            <ShieldAlert size={17} color="#06080f" strokeWidth={2.5} />
          </div>
          <div>
            <p className="font-bold text-sm tracking-wide" style={{ color: "var(--text)" }}>
              SENTINEL
            </p>
            <p className="text-[10px] font-mono" style={{ color: "var(--text-dim)" }}>
              v2026
            </p>
          </div>
        </div>

        {/* Occupancy counter */}
        <div className="mx-3 mb-5 px-3 py-3 rounded-xl glass-card-sm flex items-center justify-between">
          <span className="text-xs" style={{ color: "var(--text-dim)" }}>В зале</span>
          <span className="text-2xl font-bold font-mono" style={{ color: "var(--accent)" }}>
            {occupancy}
          </span>
        </div>

        {/* Nav */}
        <nav className="flex-1 flex flex-col gap-0.5 px-2">
          {tabs.map(({ id, label, icon: Icon }) => {
            const active = activeTab === id;
            const isAdmin = id === "admin";
            return (
              <button
                key={id}
                onClick={() => onTabChange(id)}
                aria-label={label}
                className="flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 w-full text-left"
                style={{
                  background: active
                    ? isAdmin ? "rgba(192,132,252,0.12)" : "var(--accent-dim)"
                    : "transparent",
                  color: active
                    ? isAdmin ? "#c084fc" : "var(--accent)"
                    : "var(--text-dim)",
                  border: active
                    ? `1px solid ${isAdmin ? "rgba(192,132,252,0.25)" : "rgba(0,229,255,0.15)"}`
                    : "1px solid transparent",
                }}
              >
                <Icon size={18} strokeWidth={active ? 2.5 : 1.5} />
                <span className="text-sm font-medium">{label}</span>
              </button>
            );
          })}
        </nav>

        {/* AI Chat */}
        <div className="px-2 mt-3 space-y-2">
          <button
            onClick={onChatToggle}
            aria-label="AI Ассистент"
            className="flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all w-full text-left glow-purple"
            style={{
              background: "rgba(124,58,237,0.1)",
              color: "#a78bfa",
              border: "1px solid rgba(124,58,237,0.25)",
            }}
          >
            <Bot size={18} />
            <span className="text-sm font-medium">AI Ассистент</span>
          </button>

          {unreadAlerts > 0 && (
            <button
              onClick={clearAlerts}
              aria-label={`${unreadAlerts} алертов — очистить`}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs w-full"
              style={{
                background: "rgba(255,59,92,0.08)",
                color: "var(--red)",
                border: "1px solid rgba(255,59,92,0.25)",
              }}
            >
              <ShieldAlert size={14} />
              <span>{unreadAlerts} алерт(а)</span>
            </button>
          )}

          <HealthPanel />
        </div>
      </aside>

      {/* ── Mobile bottom nav (< lg) ──────────────────────────── */}
      <nav
        className="lg:hidden fixed bottom-0 left-0 right-0 z-40 glass-surface border-t flex items-stretch justify-around"
        style={{
          height: 60,
          paddingBottom: "env(safe-area-inset-bottom, 0px)",
          borderColor: "var(--glass-border)",
        }}
      >
        {tabs.map(({ id, label, icon: Icon }) => {
          const active = activeTab === id;
          const isAdmin = id === "admin";
          return (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              aria-label={label}
              className="flex flex-col items-center justify-center gap-0.5 flex-1 min-w-[40px] min-h-[44px] transition-colors duration-150"
              style={{
                color: active
                  ? isAdmin ? "#c084fc" : "var(--accent)"
                  : "var(--text-dim)",
              }}
            >
              <Icon size={18} strokeWidth={active ? 2.5 : 1.5} />
              <span className="text-[9px] font-medium leading-none">{label}</span>
            </button>
          );
        })}
        <button
          onClick={onChatToggle}
          aria-label="AI Ассистент"
          className="flex flex-col items-center justify-center gap-0.5 flex-1 min-w-[40px] min-h-[44px]"
          style={{ color: "#a78bfa" }}
        >
          <Bot size={18} />
          <span className="text-[9px] font-medium leading-none">AI</span>
        </button>
      </nav>
    </>
  );
}
