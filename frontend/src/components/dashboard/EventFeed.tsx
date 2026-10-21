"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { useSentinelStore, type SentinelEvent, type EventType } from "@/lib/store";
import { motion, AnimatePresence } from "framer-motion";
import { formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import {
  AlertTriangle,
  Ban,
  Brain,
  Camera,
  CameraOff,
  ChevronUp,
  Clock,
  Eye,
  MapPin,
  MapPinOff,
  Pause,
  PersonStanding,
  Play,
  Scan,
  ShieldAlert,
  Star,
  Trash2,
  UserCheck,
  UserMinus,
  UserPlus,
  UserX,
  Users,
  type LucideIcon,
} from "lucide-react";

const MAX_VISIBLE = 40;

const EVENT_META: Record<EventType, { label: string; color: string; icon: LucideIcon }> = {
  "person.detected": { label: "Обнаружен", color: "var(--accent)", icon: Eye },
  "person.lost": { label: "Ушёл", color: "var(--text-dim)", icon: UserX },
  "face.identified": { label: "Идентифицирован", color: "var(--green)", icon: UserCheck },
  "face.unknown": { label: "Незнакомец", color: "var(--yellow)", icon: Scan },
  "client.entered": { label: "Клиент вошёл", color: "var(--green)", icon: UserPlus },
  "client.left": { label: "Клиент ушёл", color: "var(--text-dim)", icon: PersonStanding },
  "vip.detected": { label: "VIP!", color: "var(--green)", icon: Star },
  "staff.detected": { label: "Персонал", color: "var(--accent)", icon: Users },
  "fraud.alert": { label: "ТРЕВОГА", color: "var(--red)", icon: ShieldAlert },
  "zone.violation": { label: "Нарушение зоны", color: "var(--red)", icon: Ban },
  "zone.entered": { label: "Вошёл в зону", color: "var(--accent)", icon: MapPin },
  "zone.exited": { label: "Покинул зону", color: "var(--text-dim)", icon: MapPinOff },
  "staff.absent": { label: "Замечание: ресепшен пуст", color: "var(--red)", icon: UserMinus },
  "client.unattended": { label: "Замечание: Гость без встречи", color: "var(--yellow)", icon: Clock },
  "heatmap.update": { label: "Тепловая карта", color: "var(--text-dim)", icon: Eye },
  "occupancy.update": { label: "Заполненность", color: "var(--accent)", icon: Users },
  "llm.summary": { label: "AI Сводка", color: "var(--ai)", icon: Brain },
  "camera.online": { label: "Камера онлайн", color: "var(--green)", icon: Camera },
  "camera.offline": { label: "Камера офлайн", color: "var(--red)", icon: CameraOff },
  "pipeline.error": { label: "Ошибка", color: "var(--red)", icon: AlertTriangle },
};

const HIDDEN_TYPES = new Set(["heatmap.update", "occupancy.update"]);

export function EventFeed() {
  const events = useSentinelStore((s) => s.events);
  const clearEvents = useSentinelStore((s) => s.clearEvents);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);

  const filtered = events.filter((e) => !HIDDEN_TYPES.has(e.type));
  const visible = filtered.slice(0, MAX_VISIBLE);

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [events.length, autoScroll]);

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return;
    setAutoScroll(scrollRef.current.scrollTop < 10);
  }, []);

  const total = filtered.length;

  return (
    <div className="h-full flex flex-col rounded-xl overflow-hidden glass-card">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: "var(--text-dim)" }}>
            Поток
          </span>
          {!paused && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full opacity-75" style={{ background: "var(--green)" }} />
              <span className="relative inline-flex rounded-full h-2 w-2" style={{ background: "var(--green)" }} />
            </span>
          )}
          <span className="text-[10px] font-mono" style={{ color: "var(--text-dim)" }}>
            {total}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setPaused((p) => !p)}
            aria-label={paused ? "Возобновить поток" : "Поставить на паузу"}
            className="p-1.5 rounded-lg transition-colors hover:bg-[var(--surface-2)]"
            style={{ color: paused ? "var(--yellow)" : "var(--text-dim)" }}
          >
            {paused ? <Play size={13} /> : <Pause size={13} />}
          </button>
          <button
            onClick={clearEvents}
            aria-label="Очистить события"
            className="p-1.5 rounded-lg transition-colors hover:bg-[var(--surface-2)]"
            style={{ color: "var(--text-dim)" }}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Scroll-to-top indicator */}
      {!autoScroll && (
        <button
          onClick={() => {
            if (scrollRef.current) scrollRef.current.scrollTop = 0;
            setAutoScroll(true);
          }}
          aria-label="К новым событиям"
          className="shrink-0 w-full py-1.5 text-[10px] font-mono text-center flex items-center justify-center gap-1 transition-colors"
          style={{ background: "var(--accent)", color: "#06080f" }}
        >
          <ChevronUp size={12} />
          Новые события
        </button>
      )}

      {/* Events list */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overscroll-contain p-1.5 space-y-1"
      >
        <AnimatePresence mode="popLayout" initial={false}>
          {visible.map((event, i) => (
            <EventRow key={event.id} event={event} animate={i < 5} />
          ))}
        </AnimatePresence>

        {filtered.length === 0 && (
          <div
            className="flex flex-col items-center justify-center h-32 text-xs font-mono gap-2"
            style={{ color: "var(--text-dim)" }}
          >
            <Eye size={20} className="opacity-30" />
            Ожидание событий…
          </div>
        )}
      </div>

      {/* Footer */}
      {total > MAX_VISIBLE && (
        <div
          className="shrink-0 px-3 py-1.5 border-t text-[10px] font-mono text-center"
          style={{ borderColor: "var(--border)", color: "var(--text-dim)" }}
        >
          Показано {MAX_VISIBLE} из {total}
        </div>
      )}
    </div>
  );
}

function EventRow({ event, animate }: { event: SentinelEvent; animate: boolean }) {
  const meta = EVENT_META[event.type] ?? {
    label: event.type,
    color: "var(--text-dim)",
    icon: Eye,
  };

  const Icon = meta.icon;
  const isAlert = event.type === "fraud.alert" || event.type === "zone.violation" || event.type === "staff.absent" || event.type === "client.unattended";
  const isLLM = event.type === "llm.summary";

  const content = (
    <div
      className="rounded-xl px-3 py-2 flex items-start gap-2.5 cursor-default group transition-colors"
      style={{
        background: isAlert
          ? "rgba(251,113,133,0.07)"
          : isLLM
            ? "rgba(94,234,212,0.06)"
            : "var(--surface-2)",
        border: `1px solid ${isAlert ? "rgba(251,113,133,0.18)" : isLLM ? "rgba(94,234,212,0.15)" : "transparent"}`,
      }}
    >
      <div className="mt-0.5 shrink-0" style={{ color: meta.color }}>
        <Icon size={14} strokeWidth={1.5} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[11px] font-medium" style={{ color: meta.color }}>
            {meta.label}
          </span>
          {typeof event.payload.chapter === "string" && (
            <span
              className="text-[9px] px-1.5 py-0.5 rounded-md font-mono"
              style={{ background: "rgba(251,113,133,0.12)", color: "var(--red)" }}
            >
              {(event.payload.chapter as string).slice(0, 28)}
            </span>
          )}
          <span className="text-[10px] font-mono truncate" style={{ color: "var(--text-dim)" }}>
            {event.camera_id}
          </span>
        </div>

        {isLLM && typeof event.payload.narrative === "string" && (
          <div className="text-[11px] mt-0.5 leading-snug" style={{ color: "var(--text)" }}>
            {(event.payload.narrative as string).slice(0, 120)}
            {(event.payload.narrative as string).length > 120 && "…"}
          </div>
        )}

        {isAlert && typeof event.payload.description === "string" && (
          <div className="text-[11px] mt-0.5 leading-snug" style={{ color: "var(--text)" }}>
            {(event.payload.description as string).slice(0, 160)}
            {(event.payload.description as string).length > 160 && "…"}
          </div>
        )}
        {isAlert && typeof event.payload.action === "string" && (
          <div className="text-[10px] mt-1 leading-snug" style={{ color: "var(--accent)" }}>
            → {(event.payload.action as string).slice(0, 100)}
          </div>
        )}

        {!isLLM && !isAlert && typeof event.payload.name === "string" && (
          <div className="text-[11px] mt-0.5 flex items-center gap-1" style={{ color: "var(--text)" }}>
            <span>{event.payload.name as string}</span>
            {typeof event.payload.category === "string" && (
              <span className={`px-1 py-px rounded text-[9px] font-mono badge-${event.payload.category as string}`}>
                {event.payload.category as string}
              </span>
            )}
          </div>
        )}

        <div className="text-[9px] mt-0.5 font-mono" style={{ color: "var(--text-dim)", opacity: 0.6 }}>
          {formatDistanceToNow(new Date(event.timestamp_ms), { addSuffix: true, locale: ru })}
        </div>
      </div>
    </div>
  );

  if (!animate) return <div>{content}</div>;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
      transition={{ duration: 0.12, ease: "easeOut" }}
    >
      {content}
    </motion.div>
  );
}
