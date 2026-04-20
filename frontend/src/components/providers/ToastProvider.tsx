"use client";

import { Toaster } from "react-hot-toast";

export function ToastProvider() {
  return (
    <Toaster
      position="bottom-right"
      toastOptions={{
        style: {
          background: "#0d1117",
          color: "#e2e8f0",
          border: "1px solid #1e2738",
          fontFamily: "var(--font-inter)",
        },
        success: { iconTheme: { primary: "#00ff87", secondary: "#06080f" } },
        error: { iconTheme: { primary: "#ff3b5c", secondary: "#06080f" } },
      }}
    />
  );
}
