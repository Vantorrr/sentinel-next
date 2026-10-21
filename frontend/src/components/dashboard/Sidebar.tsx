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
      <aside className="hidden lg:flex w-64 flex-col py-5 border-r shrink-0 glass-surface relative z-[2]">
        <div className="px-4 mb-6 flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 glow-cyan"
            style={{ background: "linear-gradient(135deg, #22d3ee, #2dd4bf)" }}
          >
            <ShieldAlert size={18} color="#061018" strokeWidth={2.5} />
          </div>
          <div>
            <p className="font-display font-bold text-[15px] tracking-wide" style={{ color: "var(--text)" }}>
              SENTINEL
            </p>
            <p className="text-[10px] font-mono tracking-wider" style={{ color: "var(--text-dim)" }}>
              NEXT · 2026
            </p>
          </div>
        </div>

        <div className="mx-3 mb-5 px-3.5 py-3.5 rounded-2xl glass-card-sm flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-[0.14em] font-mono" style={{ color: "var(--text-dim)" }}>
              В зале
            </p>
            <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>сейчас онлайн</p>
          </div>
          <span className="text-3xl font-bold font-mono" style={{ color: "var(--accent)" }}>
            {occupancy}
          </span>
        </div>

        <nav className="flex-1 flex flex-col gap-1 px-2.5">
          {tabs.map(({ id, label, icon: Icon }) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                onClick={() => onTabChange(id)}
                aria-label={label}
                className={`flex items-center gap-3 px-3.5 py-2.5 rounded-xl transition-all duration-200 w-full text-left ${
                  active ? "glass-nav-active" : ""
                }`}
                style={{
                  background: active ? undefined : "transparent",
                  color: active ? undefined : "var(--text-dim)",
                  border: active ? undefined : "1px solid transparent",
                }}
              >
                <Icon size={18} strokeWidth={active ? 2.4 : 1.6} />
                <span className="text-sm font-medium">{label}</span>
              </button>
            );
          })}
        </nav>

        <div className="px-2.5 mt-3 space-y-2">
          <button
            onClick={onChatToggle}
            aria-label="AI Ассистент"
            className="flex items-center gap-3 px-3.5 py-2.5 rounded-xl transition-all w-full text-left glass-card-sm"
            style={{
              color: "var(--ai)",
              borderColor: "rgba(94,234,212,0.22)",
            }}
          >
            <Bot size={18} />
            <span className="text-sm font-medium">AI Ассистент</span>
          </button>

          {unreadAlerts > 0 && (
            <button
              onClick={clearAlerts}
              aria-label={`${unreadAlerts} алертов — очистить`}
              className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-xs w-full glass-card-sm"
              style={{
                color: "var(--red)",
                borderColor: "rgba(251,113,133,0.25)",
              }}
            >
              <ShieldAlert size={14} />
              <span>{unreadAlerts} алерт(а)</span>
            </button>
          )}

          <HealthPanel />
        </div>
      </aside>

      <nav
        className="lg:hidden fixed bottom-0 left-0 right-0 z-40 glass-surface border-t flex items-stretch overflow-x-auto no-scrollbar"
        style={{
          height: 64,
          paddingBottom: "env(safe-area-inset-bottom, 0px)",
          borderColor: "var(--glass-border)",
          WebkitOverflowScrolling: "touch",
        }}
      >
        {tabs.map(({ id, label, icon: Icon }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => onTabChange(id)}
              aria-label={label}
              className="flex flex-col items-center justify-center gap-1 shrink-0 min-w-[56px] px-2 min-h-[44px] transition-colors duration-150"
              style={{ color: active ? "var(--accent)" : "var(--text-dim)" }}
            >
              <Icon size={18} strokeWidth={active ? 2.4 : 1.6} />
              <span className="text-[9px] font-medium leading-none whitespace-nowrap">{label}</span>
            </button>
          );
        })}
        <button
          onClick={onChatToggle}
          aria-label="AI Ассистент"
          className="flex flex-col items-center justify-center gap-1 shrink-0 min-w-[56px] px-2 min-h-[44px]"
          style={{ color: "var(--ai)" }}
        >
          <Bot size={18} />
          <span className="text-[9px] font-medium leading-none">AI</span>
        </button>
      </nav>
    </>
  );
}
