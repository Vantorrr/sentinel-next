"use client";

import React, { Component } from "react";

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: string;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: "" };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error: error.message };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[Sentinel ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div
            className="flex flex-col items-center justify-center h-full gap-4 p-8"
            style={{ color: "var(--text-dim)" }}
          >
            <div
              className="text-sm px-6 py-4 rounded-xl max-w-md text-center"
              style={{
                background: "var(--surface)",
                border: "1px solid rgba(255,59,92,0.3)",
              }}
            >
              <p className="text-xs font-mono mb-2" style={{ color: "var(--red)" }}>
                RUNTIME ERROR
              </p>
              <p className="text-xs" style={{ color: "var(--text-dim)" }}>
                {this.state.error}
              </p>
              <button
                onClick={() => this.setState({ hasError: false, error: "" })}
                className="mt-4 text-xs px-4 py-1.5 rounded-lg"
                style={{
                  background: "var(--accent-dim)",
                  color: "var(--accent)",
                  border: "1px solid rgba(0,229,255,0.2)",
                }}
              >
                Перезагрузить
              </button>
            </div>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
