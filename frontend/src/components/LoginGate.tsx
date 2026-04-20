"use client";

import { useState, useEffect, type ReactNode, type FormEvent } from "react";
import { authApi } from "@/lib/api";
import { ShieldAlert, AlertCircle, Loader2 } from "lucide-react";

interface Props {
  children: ReactNode;
}

type LoginMode = "email" | "apikey";

export default function LoginGate({ children }: Props) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [mode, setMode] = useState<LoginMode>("email");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setAuthed(authApi.isAuthenticated());
    const handler = () => setAuthed(false);
    window.addEventListener("sentinel:auth-required", handler);
    return () => window.removeEventListener("sentinel:auth-required", handler);
  }, []);

  if (authed === null) {
    return (
      <div className="fixed inset-0 z-[9999] flex items-center justify-center" style={{ background: "var(--bg)" }}>
        <div className="flex flex-col items-center gap-4">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center glow-cyan"
            style={{ background: "var(--accent)", animation: "float 2s ease-in-out infinite" }}
          >
            <ShieldAlert size={28} color="#06080f" strokeWidth={2} />
          </div>
          <div className="w-32 h-1 rounded-full skeleton" />
        </div>
      </div>
    );
  }

  if (authed) return <>{children}</>;

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (mode === "email") {
        await authApi.loginWithEmail(email, password);
      } else {
        await authApi.loginWithApiKey(apiKey);
      }
      setAuthed(true);
    } catch {
      setError(mode === "email" ? "Неверный email или пароль" : "Неверный ключ доступа");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center p-4" style={{ background: "var(--bg)" }}>
      {/* Animated background */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute w-[600px] h-[600px] rounded-full opacity-[0.03]"
          style={{
            background: "radial-gradient(circle, var(--accent), transparent 70%)",
            top: "-20%",
            right: "-10%",
            animation: "float 8s ease-in-out infinite",
          }}
        />
        <div
          className="absolute w-[400px] h-[400px] rounded-full opacity-[0.04]"
          style={{
            background: "radial-gradient(circle, var(--accent-2), transparent 70%)",
            bottom: "-10%",
            left: "-10%",
            animation: "float 6s ease-in-out infinite reverse",
          }}
        />
      </div>

      <form
        onSubmit={handleLogin}
        className="w-full max-w-sm space-y-5 glass-card p-8 shadow-2xl relative border-glow"
      >
        <div className="text-center">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4 glow-cyan"
            style={{ background: "var(--accent)" }}
          >
            <ShieldAlert size={28} color="#06080f" strokeWidth={2} />
          </div>
          <h1 className="text-xl font-bold" style={{ color: "var(--text)" }}>
            Sentinel-Next
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--text-muted)" }}>
            Авторизация
          </p>
        </div>

        {/* Mode switcher */}
        <div className="flex rounded-xl glass-card-sm overflow-hidden p-0.5" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "email"}
            onClick={() => setMode("email")}
            className="flex-1 py-2 text-xs font-medium rounded-lg transition-all duration-200"
            style={{
              background: mode === "email" ? "var(--accent)" : "transparent",
              color: mode === "email" ? "#06080f" : "var(--text-muted)",
            }}
          >
            Email
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "apikey"}
            onClick={() => setMode("apikey")}
            className="flex-1 py-2 text-xs font-medium rounded-lg transition-all duration-200"
            style={{
              background: mode === "apikey" ? "var(--accent)" : "transparent",
              color: mode === "apikey" ? "#06080f" : "var(--text-muted)",
            }}
          >
            API Key
          </button>
        </div>

        {mode === "email" ? (
          <>
            <div>
              <label htmlFor="login-email" className="sr-only">Email</label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                autoFocus
                className="w-full glass-input px-4 py-3 text-sm"
              />
            </div>
            <div>
              <label htmlFor="login-password" className="sr-only">Пароль</label>
              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Пароль"
                className="w-full glass-input px-4 py-3 text-sm"
              />
            </div>
          </>
        ) : (
          <div>
            <label htmlFor="login-apikey" className="sr-only">API Key</label>
            <input
              id="login-apikey"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="API Key (sk-...)"
              autoFocus
              className="w-full glass-input px-4 py-3 text-sm font-mono"
            />
          </div>
        )}

        {error && (
          <div
            className="flex items-center gap-2 px-3 py-2.5 rounded-xl text-sm"
            style={{
              background: "rgba(255,59,92,0.08)",
              border: "1px solid rgba(255,59,92,0.2)",
              color: "var(--red)",
            }}
          >
            <AlertCircle size={14} className="shrink-0" />
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading || (mode === "email" ? !email || !password : !apiKey)}
          className="w-full rounded-xl px-4 py-3 font-medium text-sm transition-all duration-200 disabled:opacity-40 flex items-center justify-center gap-2"
          style={{
            background: "var(--accent)",
            color: "#06080f",
            boxShadow: "0 0 24px var(--accent-glow)",
          }}
        >
          {loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Проверка…
            </>
          ) : (
            "Войти"
          )}
        </button>
      </form>
    </div>
  );
}
