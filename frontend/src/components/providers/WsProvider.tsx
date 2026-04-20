"use client";

import { useEffect } from "react";
import { connectEventStream, disconnectEventStream } from "@/lib/ws";
import { startDemoMode, stopDemoMode } from "@/lib/demo";
import { useSentinelStore } from "@/lib/store";

const DEMO_FALLBACK_TIMEOUT_MS = 5000;

export function WsProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    // Check for explicit demo mode via URL param or env
    const isDemoUrl = typeof window !== "undefined" && window.location.search.includes("demo=1");

    if (isDemoUrl) {
      startDemoMode();
      return () => stopDemoMode();
    }

    connectEventStream();

    // If WebSocket doesn't connect within timeout, fall back to demo
    const fallbackTimer = setTimeout(() => {
      const connected = useSentinelStore.getState().wsConnected;
      if (!connected) {
        console.info("[Sentinel] Backend unreachable — activating demo mode");
        startDemoMode();
      }
    }, DEMO_FALLBACK_TIMEOUT_MS);

    return () => {
      clearTimeout(fallbackTimer);
      disconnectEventStream();
      stopDemoMode();
    };
  }, []);

  return <>{children}</>;
}
