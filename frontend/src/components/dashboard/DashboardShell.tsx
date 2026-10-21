"use client";

import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useSentinelStore } from "@/lib/store";
import { authApi } from "@/lib/api";
import { LogOut, Menu, ShieldAlert } from "lucide-react";
import { Sidebar } from "./Sidebar";
import { OverviewPanel } from "./OverviewPanel";
import { EventFeed } from "./EventFeed";
import { CameraGrid } from "./CameraGrid";
import { ChatDrawer } from "./ChatDrawer";
import { HeatmapView } from "./HeatmapView";
import { AnalyticsPanel } from "./AnalyticsPanel";
import { PersonsPanel } from "./PersonsPanel";
import { ZonesPanel } from "./ZonesPanel";
import { ErrorBoundary } from "../ErrorBoundary";
import { AdminPanel } from "../admin/AdminPanel";

export type Tab = "overview" | "cameras" | "zones" | "heatmap" | "analytics" | "persons" | "admin";

export function DashboardShell() {
  const [tab, setTab] = useState<Tab>("overview");
  const [chatOpen, setChatOpen] = useState(false);
  const isSuperadmin = authApi.isSuperadmin();

  return (
    <div className="flex h-screen overflow-hidden relative">
      <div className="atmosphere opacity-60" />

      <Sidebar
        activeTab={tab}
        onTabChange={setTab}
        onChatToggle={() => setChatOpen((o) => !o)}
        showAdmin={isSuperadmin}
      />

      <main className="flex-1 flex flex-col overflow-hidden relative z-[1]">
        <TopBar />

        <ErrorBoundary>
          <div className="flex-1 overflow-hidden p-3 lg:p-4 gap-3 lg:gap-4 flex flex-col pb-[76px] lg:pb-4">
            <AnimatePresence mode="wait">
              <motion.div
                key={tab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.22, ease: "easeOut" }}
                className="flex-1 min-h-0 flex flex-col"
              >
                {tab === "overview" && (
                  <div className="grid grid-cols-1 lg:grid-cols-12 gap-3 lg:gap-4 flex-1 min-h-0">
                    <div className="col-span-1 lg:col-span-8 flex flex-col gap-3 lg:gap-4 overflow-y-auto min-h-0">
                      <OverviewPanel />
                      <CameraGrid compact />
                    </div>
                    <div className="col-span-1 lg:col-span-4 min-h-0 max-h-[50vh] lg:max-h-none">
                      <EventFeed />
                    </div>
                  </div>
                )}
                {tab === "cameras" && <div className="flex-1 min-h-0 overflow-y-auto"><CameraGrid /></div>}
                {tab === "zones" && <div className="flex-1 min-h-0 overflow-y-auto"><ZonesPanel /></div>}
                {tab === "heatmap" && <div className="flex-1 min-h-0 overflow-y-auto"><HeatmapView /></div>}
                {tab === "analytics" && <div className="flex-1 min-h-0 overflow-y-auto"><AnalyticsPanel /></div>}
                {tab === "persons" && <div className="flex-1 min-h-0 overflow-y-auto"><PersonsPanel /></div>}
                {tab === "admin" && isSuperadmin && <div className="flex-1 min-h-0 overflow-y-auto"><AdminPanel /></div>}
              </motion.div>
            </AnimatePresence>
          </div>
        </ErrorBoundary>
      </main>

      {chatOpen && <ChatDrawer onClose={() => setChatOpen(false)} />}
    </div>
  );
}

function TopBar() {
  const wsConnected = useSentinelStore((s) => s.wsConnected);
  const user = authApi.getUser();
  const [menuOpen, setMenuOpen] = useState(false);

  const handleLogout = () => {
    authApi.logout();
    window.location.reload();
  };

  return (
    <header className="flex items-center justify-between px-4 lg:px-6 py-2.5 lg:py-3 border-b glass-surface shrink-0 relative z-[2]">
      <div className="flex items-center gap-3">
        <div className="lg:hidden flex items-center gap-2.5">
          <div
            className="w-8 h-8 rounded-xl flex items-center justify-center glow-cyan"
            style={{ background: "linear-gradient(135deg, #22d3ee, #2dd4bf)" }}
          >
            <ShieldAlert size={15} color="#061018" strokeWidth={2.5} />
          </div>
          <span className="font-display text-sm font-bold tracking-wide" style={{ color: "var(--text)" }}>
            SENTINEL
          </span>
        </div>

        <span
          className="hidden lg:block text-[11px] font-mono uppercase tracking-[0.18em]"
          style={{ color: "var(--text-dim)" }}
        >
          Sentinel-Next · 2026
        </span>

        {user?.tenant_name && (
          <span
            className="hidden sm:inline-block text-xs px-2.5 py-1 rounded-xl glass-card-sm font-medium"
            style={{ color: "var(--accent)" }}
          >
            {user.tenant_name}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 lg:gap-3">
        <div
          className="relative flex items-center gap-1.5 lg:gap-2 px-2.5 lg:px-3 py-1.5 rounded-xl text-xs font-mono glass-card-sm"
          style={{ color: wsConnected ? "var(--green)" : "var(--red)" }}
        >
          <span className={wsConnected ? "live-dot" : "w-2 h-2 rounded-full"} style={{ background: wsConnected ? undefined : "var(--red)" }} />
          <span className="hidden sm:inline">{wsConnected ? "LIVE" : "OFFLINE"}</span>
        </div>

        {user && (
          <div className="hidden lg:flex items-center gap-2">
            <span className="text-xs" style={{ color: "var(--text-dim)" }}>{user.email}</span>
            <button
              onClick={handleLogout}
              aria-label="Выйти"
              className="text-xs px-3 py-1.5 rounded-xl glass-card-sm transition-colors hover:opacity-90"
              style={{ color: "var(--text-dim)" }}
            >
              Выйти
            </button>
          </div>
        )}

        <div className="lg:hidden relative">
          <button
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Меню"
            className="p-2 rounded-xl glass-card-sm"
            style={{ color: "var(--text-dim)" }}
          >
            <Menu size={18} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full mt-2 z-50 w-52 rounded-2xl p-2 glass-card space-y-1">
                {user && (
                  <div className="px-3 py-2 text-xs truncate" style={{ color: "var(--text-dim)" }}>
                    {user.email}
                  </div>
                )}
                {user?.tenant_name && (
                  <div className="px-3 py-1.5 text-xs font-medium" style={{ color: "var(--accent)" }}>
                    {user.tenant_name}
                  </div>
                )}
                <button
                  onClick={handleLogout}
                  className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-xs transition-colors"
                  style={{ color: "var(--red)" }}
                >
                  <LogOut size={14} />
                  Выйти
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
