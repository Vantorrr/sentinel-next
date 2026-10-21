"use client";

import { useEffect } from "react";
import { connectEventStream, disconnectEventStream } from "@/lib/ws";

/** Product-only event stream — no synthetic demo fallback. */
export function WsProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    connectEventStream();
    return () => disconnectEventStream();
  }, []);

  return <>{children}</>;
}
