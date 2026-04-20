import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { WsProvider } from "@/components/providers/WsProvider";
import { ToastProvider } from "@/components/providers/ToastProvider";
import LoginGate from "@/components/LoginGate";
import { PwaRegistration } from "@/components/PwaRegistration";
import { InstallPrompt } from "@/components/InstallPrompt";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Sentinel-Next | AI Surveillance Platform",
  description: "Multi-tenant AI-powered business surveillance SaaS",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Sentinel",
  },
};

export const viewport: Viewport = {
  themeColor: "#06080f",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={`${inter.variable} ${mono.variable}`}>
      <head>
        <link rel="apple-touch-icon" href="/icon-192.png" />
      </head>
      <body>
        <PwaRegistration />
        <LoginGate>
          <WsProvider>
            <ToastProvider />
            {children}
            <InstallPrompt />
          </WsProvider>
        </LoginGate>
      </body>
    </html>
  );
}
