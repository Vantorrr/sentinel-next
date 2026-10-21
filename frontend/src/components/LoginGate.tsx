"use client";

import { useState, useEffect, type ReactNode, type FormEvent } from "react";
import { authApi } from "@/lib/api";
import { ShieldAlert, AlertCircle, Loader2, KeyRound, Mail } from "lucide-react";

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
        <div className="atmosphere" />
        <div className="flex flex-col items-center gap-4 panel-enter">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center glow-cyan"
            style={{ background: "linear-gradient(135deg, #22d3ee, #2dd4bf)", animation: "float 2.4s ease-in-out infinite" }}
          >
            <ShieldAlert size={28} color="#061018" strokeWidth={2} />
          </div>
          <div className="w-36 h-1.5 rounded-full skeleton" />
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
      <div className="atmosphere" />
      <div className="atmosphere-grid" />

      <form
        onSubmit={handleLogin}
        className="w-full max-w-[400px] space-y-6 glass-card p-8 relative border-glow panel-enter"
      >
        <div className="text-center space-y-3">
          <div
            className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto glow-cyan"
            style={{ background: "linear-gradient(135deg, #22d3ee, #2dd4bf)" }}
          >
            <ShieldAlert size={30} color="#061018" strokeWidth={2.2} />
          </div>
          <div>
            <h1 className="font-display text-3xl font-bold tracking-tight" style={{ color: "var(--text)" }}>
              SENTINEL
            </h1>
            <p className="mt-1.5 text-sm leading-relaxed" style={{ color: "var(--text-dim)" }}>
              AI-платформа контроля салонов. Один вход — все объекты.
            </p>
          </div>
        </div>

        <div className="flex rounded-2xl glass-card-sm overflow-hidden p-1" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "email"}
            onClick={() => setMode("email")}
            className="flex-1 py-2.5 text-xs font-semibold rounded-xl transition-all duration-200 flex items-center justify-center gap-1.5"
            style={{
              background: mode === "email" ? "linear-gradient(135deg, #22d3ee, #2dd4bf)" : "transparent",
              color: mode === "email" ? "#061018" : "var(--text-muted)",
            }}
          >
            <Mail size={13} />
            Email
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "apikey"}
            onClick={() => setMode("apikey")}
            className="flex-1 py-2.5 text-xs font-semibold rounded-xl transition-all duration-200 flex items-center justify-center gap-1.5"
            style={{
              background: mode === "apikey" ? "linear-gradient(135deg, #22d3ee, #2dd4bf)" : "transparent",
              color: mode === "apikey" ? "#061018" : "var(--text-muted)",
            }}
          >
            <KeyRound size={13} />
            API Key
          </button>
        </div>

        {mode === "email" ? (
          <div className="space-y-3">
            <div>
              <label htmlFor="login-email" className="sr-only">Email</label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                autoFocus
                autoComplete="email"
                className="w-full glass-input px-4 py-3.5 text-sm"
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
                autoComplete="current-password"
                className="w-full glass-input px-4 py-3.5 text-sm"
              />
            </div>
          </div>
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
              className="w-full glass-input px-4 py-3.5 text-sm font-mono"
            />
          </div>
        )}

        {error && (
          <div
            className="flex items-center gap-2 px-3.5 py-3 rounded-xl text-sm"
            style={{
              background: "rgba(251,113,133,0.08)",
              border: "1px solid rgba(251,113,133,0.22)",
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
          className="w-full btn-accent px-4 py-3.5 text-sm flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Проверка…
            </>
          ) : (
            "Войти в систему"
          )}
        </button>
      </form>
    </div>
  );
}
