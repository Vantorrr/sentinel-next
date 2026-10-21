import type { Metadata, Viewport } from "next";
import { Outfit, Syne, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { WsProvider } from "@/components/providers/WsProvider";
import { ToastProvider } from "@/components/providers/ToastProvider";
import LoginGate from "@/components/LoginGate";
import { PwaRegistration } from "@/components/PwaRegistration";
import { InstallPrompt } from "@/components/InstallPrompt";

const outfit = Outfit({
  subsets: ["latin", "latin-ext"],
  variable: "--font-outfit",
  display: "swap",
});

const syne = Syne({
  subsets: ["latin"],
  variable: "--font-syne",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

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
  themeColor: "#07090f",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={`${outfit.variable} ${syne.variable} ${mono.variable}`}>
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
