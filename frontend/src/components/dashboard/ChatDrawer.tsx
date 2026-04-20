"use client";

import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, Mic, MicOff, Send, X } from "lucide-react";
import toast from "react-hot-toast";
import { chatApi, type ChatMessage } from "@/lib/api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const WS_CHAT_URL =
  process.env.NEXT_PUBLIC_WS_URL?.replace("/ws/events", "/api/v1/chat/ws") ??
  "ws://localhost:8000/api/v1/chat/ws";

export function ChatDrawer({ onClose }: { onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Привет! Я Sentinel AI. Спросите меня о посетителях, событиях или аналитике.\n\n" +
        "Например: «Кто сегодня заходил?» или «Есть ли алерты?»",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const token = typeof window !== "undefined"
      ? localStorage.getItem("sentinel_token") ?? ""
      : "";
    const sep = WS_CHAT_URL.includes("?") ? "&" : "?";
    const url = token ? `${WS_CHAT_URL}${sep}token=${encodeURIComponent(token)}` : WS_CHAT_URL;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (msg) => {
      const data = JSON.parse(msg.data as string);
      if (data.answer) {
        setMessages((m) => [...m, { role: "assistant", content: data.answer }]);
        setLoading(false);
        speak(data.answer);
      }
    };

    ws.onerror = () => {
      wsRef.current = null;
    };

    return () => ws.close();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;
    const msg: Message = { role: "user", content: text };
    const updatedMessages = [...messages, msg];
    setMessages(updatedMessages);
    setInput("");
    setLoading(true);

    const history: ChatMessage[] = updatedMessages.slice(-10).map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ question: text, history }));
    } else {
      try {
        const data = await chatApi.ask(text, history);
        setMessages((m) => [...m, { role: "assistant", content: data.answer }]);
        speak(data.answer);
      } catch {
        toast.error("Ошибка связи с AI");
      } finally {
        setLoading(false);
      }
    }
  }

  function speak(text: string) {
    if (!("speechSynthesis" in window)) return;
    const utter = new SpeechSynthesisUtterance(text.slice(0, 500));
    utter.lang = "ru-RU";
    utter.rate = 1.1;
    window.speechSynthesis.speak(utter);
  }

  async function toggleVoice() {
    if (recording) {
      setRecording(false);
      return;
    }

    if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
      toast.error("Голосовой ввод не поддерживается");
      return;
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SR: any = (window as any).SpeechRecognition ?? (window as any).webkitSpeechRecognition;
    const recognition = new SR();
    recognition.lang = "ru-RU";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    recognition.onresult = (event: any) => {
      const transcript = event.results[0][0].transcript;
      sendMessage(transcript);
    };

    recognition.onerror = () => toast.error("Ошибка распознавания речи");
    recognition.onend = () => setRecording(false);

    recognition.start();
    setRecording(true);
  }

  return (
    <>
      {/* Backdrop on mobile */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="sm:hidden fixed inset-0 z-30 modal-backdrop"
        onClick={onClose}
      />

      <motion.aside
        initial={{ x: "100%" }}
        animate={{ x: 0 }}
        exit={{ x: "100%" }}
        transition={{ type: "spring", damping: 25, stiffness: 200 }}
        className="w-full sm:w-96 flex flex-col border-l h-screen glass-surface fixed right-0 top-0 z-40"
        style={{
          borderColor: "var(--glass-border)",
          paddingBottom: "env(safe-area-inset-bottom, 0px)",
        }}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-4 border-b shrink-0" style={{ borderColor: "var(--border)" }}>
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center glow-purple"
            style={{ background: "rgba(124,58,237,0.2)", border: "1px solid rgba(124,58,237,0.4)" }}
          >
            <Bot size={16} style={{ color: "#a78bfa" }} />
          </div>
          <div>
            <p className="text-sm font-semibold">AI Ассистент</p>
            <p className="text-[11px]" style={{ color: "var(--text-dim)" }}>
              Claude 3.5 · Sentinel Intelligence
            </p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-[var(--surface-2)] transition-colors" style={{ color: "var(--text-dim)" }} aria-label="Закрыть чат">
            <X size={18} />
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <AnimatePresence initial={false}>
            {messages.map((msg, i) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap ${
                    msg.role === "user" ? "rounded-2xl rounded-br-md" : "rounded-2xl rounded-bl-md glass-card-sm"
                  }`}
                  style={
                    msg.role === "user"
                      ? {
                          background: "rgba(0,229,255,0.1)",
                          border: "1px solid rgba(0,229,255,0.2)",
                          color: "var(--text)",
                        }
                      : {
                          color: "var(--text)",
                        }
                  }
                >
                  {msg.content}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {loading && (
            <div className="flex justify-start">
              <div className="px-4 py-3 rounded-2xl rounded-bl-md text-sm glass-card-sm">
                <TypingDots />
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t shrink-0" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center gap-2 rounded-xl px-3 py-2 glass-card-sm">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage(input)}
              placeholder="Спросите что угодно..."
              className="flex-1 bg-transparent outline-none text-sm"
              style={{ color: "var(--text)" }}
              aria-label="Сообщение для AI"
            />

            <button
              onClick={toggleVoice}
              aria-label={recording ? "Остановить запись" : "Голосовой ввод"}
              className="p-2 rounded-lg transition-colors min-w-[36px] min-h-[36px] flex items-center justify-center"
              style={{
                color: recording ? "var(--red)" : "var(--text-dim)",
                background: recording ? "rgba(255,59,92,0.1)" : "transparent",
              }}
            >
              {recording ? <MicOff size={16} /> : <Mic size={16} />}
            </button>

            <button
              onClick={() => sendMessage(input)}
              disabled={!input.trim() || loading}
              aria-label="Отправить"
              className="p-2 rounded-lg transition-colors disabled:opacity-30 min-w-[36px] min-h-[36px] flex items-center justify-center"
              style={{ color: "var(--accent)" }}
            >
              <Send size={16} />
            </button>
          </div>
          <p className="text-[10px] mt-2 text-center" style={{ color: "var(--text-dim)" }}>
            Enter — отправить · Микрофон — голосовой ввод
          </p>
        </div>
      </motion.aside>
    </>
  );
}

function TypingDots() {
  return (
    <div className="flex gap-1 items-center h-4">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="w-1.5 h-1.5 rounded-full"
          style={{
            background: "var(--text-dim)",
            animation: `bounce 1.2s ${i * 0.2}s infinite`,
          }}
        />
      ))}
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: scale(0.7); opacity: 0.5 }
          40% { transform: scale(1); opacity: 1 }
        }
      `}</style>
    </div>
  );
}
