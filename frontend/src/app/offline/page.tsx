"use client";

import { ShieldAlert, WifiOff } from "lucide-react";

export default function OfflinePage() {
  return (
    <div className="flex h-screen items-center justify-center p-4" style={{ background: "var(--bg)" }}>
      <div className="text-center space-y-5 glass-card p-8 max-w-sm w-full">
        <div
          className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
        >
          <WifiOff size={28} style={{ color: "var(--text-dim)" }} />
        </div>
        <h1 className="text-xl font-bold">Нет подключения</h1>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          Проверьте интернет-соединение и обновите страницу
        </p>
        <button
          onClick={() => window.location.reload()}
          className="rounded-xl px-6 py-2.5 text-sm font-medium transition-all"
          style={{ background: "var(--accent)", color: "#06080f" }}
        >
          Обновить
        </button>
      </div>
    </div>
  );
}
