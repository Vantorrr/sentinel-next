"use client";

import { useState, useEffect } from "react";
import { Download, X } from "lucide-react";

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (localStorage.getItem("sentinel_pwa_dismissed") === "true") {
      setDismissed(true);
      return;
    }

    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  if (!deferredPrompt || dismissed) return null;

  const install = async () => {
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === "accepted") {
      setDeferredPrompt(null);
    }
  };

  const dismiss = () => {
    setDismissed(true);
    localStorage.setItem("sentinel_pwa_dismissed", "true");
    setDeferredPrompt(null);
  };

  return (
    <div className="fixed bottom-20 lg:bottom-4 left-1/2 -translate-x-1/2 z-50 w-[calc(100%-2rem)] max-w-sm glass-card px-4 py-3 shadow-2xl glow-cyan">
      <div className="flex flex-col sm:flex-row items-center gap-3">
        <div className="flex items-center gap-3 flex-1">
          <Download size={18} style={{ color: "var(--accent)" }} className="shrink-0" />
          <span className="text-sm">Установить Sentinel</span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={install}
            className="rounded-xl px-4 py-1.5 text-sm font-medium transition-all"
            style={{ background: "var(--accent)", color: "#06080f" }}
          >
            Установить
          </button>
          <button
            onClick={dismiss}
            aria-label="Отложить установку"
            className="p-1.5 rounded-lg hover:bg-[var(--surface-2)] transition-colors"
            style={{ color: "var(--text-muted)" }}
          >
            <X size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
