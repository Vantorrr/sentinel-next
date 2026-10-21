"use client";

import { useEffect, useState } from "react";
import { useSentinelStore } from "@/lib/store";
import {
  Camera,
  CheckCircle2,
  ChevronDown,
  Cloud,
  Download,
  Loader2,
  Plus,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";
import toast from "react-hot-toast";
import { camerasApi, hikconnectApi, type AddCameraBody, type HikCamera } from "@/lib/api";

type CameraPreset = "hikvision" | "dahua" | "custom";

const PRESETS: { id: CameraPreset; label: string; desc: string }[] = [
  { id: "hikvision", label: "Hikvision", desc: "Hik-Connect / iVMS" },
  { id: "dahua", label: "Dahua", desc: "gDMSS / SmartPSS" },
  { id: "custom", label: "Другая", desc: "Ручной ввод RTSP URL" },
];

function buildRtspUrl(
  preset: CameraPreset,
  ip: string,
  port: string,
  user: string,
  pass: string,
  channel: number,
  stream: "main" | "sub",
): string {
  const auth = user && pass ? `${user}:${pass}@` : "";
  const p = port || "554";

  if (preset === "hikvision") {
    const ch = stream === "main" ? `${channel}01` : `${channel}02`;
    return `rtsp://${auth}${ip}:${p}/Streaming/Channels/${ch}`;
  }
  if (preset === "dahua") {
    const s = stream === "main" ? "0" : "1";
    return `rtsp://${auth}${ip}:${p}/cam/realmonitor?channel=${channel}&subtype=${s}`;
  }
  return "";
}

export function CameraGrid({ compact = false }: { compact?: boolean }) {
  const cameras = useSentinelStore((s) => s.cameras);
  const setCameras = useSentinelStore((s) => s.setCameras);
  const activeTracks = useSentinelStore((s) => s.activeTracks);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    let cancelled = false;
    camerasApi
      .list()
      .then((list) => {
        if (!cancelled) setCameras(list);
      })
      .catch(() => {
        /* store stays empty until WS/demo */
      });
    return () => {
      cancelled = true;
    };
  }, [setCameras]);

  async function removeCamera(id: string) {
    try {
      await camerasApi.remove(id);
      setCameras(cameras.filter((c) => c.id !== id));
      toast.success("Камера удалена");
    } catch {
      toast.error("Ошибка удаления");
    }
  }

  const gridCols = compact
    ? "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3"
    : "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

  return (
    <div className="space-y-3">
      {!compact && (
        <div className="flex items-center justify-between">
          <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--text-dim)" }}>
            Камеры ({cameras.length})
          </span>
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl transition-all glass-card-sm hover:border-[var(--accent)]"
            style={{ color: "var(--accent)" }}
          >
            <Plus size={12} />
            Добавить
          </button>
        </div>
      )}

      <div className={`grid ${gridCols} gap-2 lg:gap-3`}>
        {cameras.map((cam) => {
          const tracks = activeTracks[cam.id]?.size ?? 0;
          return (
            <div
              key={cam.id}
              className="relative rounded-xl overflow-hidden group glass-card"
              style={{
                aspectRatio: compact ? "16/9" : "16/10",
                borderColor: cam.running ? "rgba(0,229,255,0.2)" : undefined,
              }}
            >
              {/* Gradient background */}
              <div
                className="absolute inset-0"
                style={{
                  background: cam.running
                    ? "linear-gradient(135deg, rgba(0,229,255,0.03), rgba(124,58,237,0.03))"
                    : "var(--surface-2)",
                }}
              />

              {/* Camera icon placeholder */}
              <div className="absolute inset-0 flex items-center justify-center">
                <Camera
                  size={compact ? 24 : 32}
                  style={{ color: cam.running ? "var(--accent)" : "var(--text-dim)", opacity: 0.15 }}
                />
              </div>

              {/* Corner status */}
              <div className="absolute top-2 left-2 flex items-center gap-1.5">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: cam.running ? "var(--green)" : "var(--red)",
                    boxShadow: cam.running ? "0 0 6px var(--green)" : "none",
                  }}
                />
                <span className="text-[10px] font-mono" style={{ color: "var(--text)" }}>
                  {cam.name || cam.id}
                </span>
              </div>

              {/* Track count */}
              {tracks > 0 && (
                <div
                  className="absolute top-2 right-2 px-1.5 py-0.5 rounded-lg text-[10px] font-mono glass-card-sm"
                  style={{ color: "var(--accent)" }}
                >
                  {tracks}
                </div>
              )}

              {/* LIVE badge */}
              {cam.running && (
                <div
                  className="absolute bottom-2 left-2 flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-bold tracking-wider"
                  style={{ background: "rgba(255,59,92,0.8)", color: "#fff" }}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-white animate-pulse" />
                  LIVE
                </div>
              )}

              {/* Remove button — visible on mobile, hover on desktop */}
              {!compact && (
                <button
                  onClick={() => removeCamera(cam.id)}
                  aria-label={`Удалить камеру ${cam.name || cam.id}`}
                  className="absolute bottom-2 right-2 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 transition-opacity p-1.5 rounded-lg min-w-[32px] min-h-[32px] flex items-center justify-center"
                  style={{ background: "rgba(255,59,92,0.2)", color: "var(--red)" }}
                >
                  <X size={12} />
                </button>
              )}
            </div>
          );
        })}

        {/* Empty state */}
        {cameras.length === 0 && (
          <div className="col-span-full rounded-xl flex flex-col items-center justify-center py-12 text-center glass-card">
            <Camera size={32} style={{ color: "var(--text-dim)", marginBottom: 8 }} className="opacity-30" />
            <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
              Подключите камеры салона
            </p>
            <p className="text-xs mt-1.5 max-w-sm" style={{ color: "var(--text-dim)" }}>
              RTSP (Hikvision / Dahua) или Hik-Connect — живой поток, не демо.
            </p>
            <button
              onClick={() => setAdding(true)}
              className="mt-4 text-xs px-4 py-2 rounded-xl glass-card-sm hover:border-[var(--accent)] transition-colors"
              style={{ color: "var(--accent)" }}
            >
              + Добавить камеру
            </button>
          </div>
        )}
      </div>

      {adding && (
        <AddCameraModal
          onClose={() => setAdding(false)}
          onAdded={(cam) => {
            setCameras([...cameras, cam]);
            setAdding(false);
          }}
        />
      )}
    </div>
  );
}

function AddCameraModal({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: (cam: { id: string; name: string; url: string; location_id: string; enabled: boolean; running: boolean }) => void;
}) {
  const [mode, setMode] = useState<"rtsp" | "cloud">("cloud");
  const [preset, setPreset] = useState<CameraPreset>("hikvision");
  const [ip, setIp] = useState("");
  const [port, setPort] = useState("554");
  const [user, setUser] = useState("admin");
  const [pass, setPass] = useState("");
  const [channel, setChannel] = useState(1);
  const [stream, setStream] = useState<"main" | "sub">("sub");
  const [customUrl, setCustomUrl] = useState("");
  const [camName, setCamName] = useState("");
  const [camId, setCamId] = useState("");
  const [locationId, setLocationId] = useState("default");

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; width?: number; height?: number; fps?: number; error?: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const rtspUrl = preset === "custom"
    ? customUrl
    : buildRtspUrl(preset, ip, port, user, pass, channel, stream);

  const canTest = preset === "custom" ? !!customUrl : !!ip;

  async function handleTest() {
    if (!rtspUrl) return;
    setTesting(true);
    setTestResult(null);
    try {
      const result = await camerasApi.testConnection(rtspUrl);
      setTestResult(result);
      if (result.ok) toast.success(`Подключение OK — ${result.width}x${result.height}`);
      else toast.error(result.error || "Ошибка подключения");
    } catch {
      setTestResult({ ok: false, error: "Ошибка сети" });
    } finally {
      setTesting(false);
    }
  }

  async function handleAdd() {
    const id = camId || `cam-${ip.replace(/\./g, "-")}-ch${channel}`;
    const name = camName || `${PRESETS.find((p) => p.id === preset)?.label || ""} CH${channel}`;
    setSubmitting(true);
    try {
      const cam = await camerasApi.add({
        id,
        url: rtspUrl,
        name,
        location_id: locationId,
        fps_inference: stream === "sub" ? 10 : 5,
      });
      toast.success(`Камера «${cam.name}» подключена`);
      onAdded(cam);
    } catch {
      toast.error("Ошибка добавления камеры");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 modal-backdrop" onClick={onClose}>
      <div
        className="w-full max-w-lg glass-card p-6 space-y-4 shadow-2xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="font-bold text-lg" style={{ color: "var(--text)" }}>
            Подключить камеру
          </h3>
          <button onClick={onClose} className="p-1" style={{ color: "var(--text-dim)" }}>
            <X size={18} />
          </button>
        </div>

        {/* Mode selector: Cloud vs RTSP */}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => setMode("cloud")}
            className="flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all"
            style={{
              background: mode === "cloud" ? "var(--accent-dim)" : "var(--surface-2)",
              color: mode === "cloud" ? "var(--accent)" : "var(--text-dim)",
              border: mode === "cloud" ? "1px solid rgba(0,229,255,0.25)" : "1px solid transparent",
            }}
          >
            <Cloud size={16} />
            Hik-Connect Cloud
          </button>
          <button
            onClick={() => setMode("rtsp")}
            className="flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all"
            style={{
              background: mode === "rtsp" ? "var(--accent-dim)" : "var(--surface-2)",
              color: mode === "rtsp" ? "var(--accent)" : "var(--text-dim)",
              border: mode === "rtsp" ? "1px solid rgba(0,229,255,0.25)" : "1px solid transparent",
            }}
          >
            <Wifi size={16} />
            RTSP (напрямую)
          </button>
        </div>

        {mode === "cloud" && (
          <HikConnectImport onImported={(cam) => onAdded(cam)} />
        )}

        {mode === "rtsp" && <>
        {/* Preset selector */}
        <div>
          <label className="text-xs font-medium block mb-2" style={{ color: "var(--text-dim)" }}>
            Производитель
          </label>
          <div className="grid grid-cols-3 gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.id}
                onClick={() => { setPreset(p.id); setTestResult(null); }}
                className="rounded-xl px-3 py-2.5 text-left transition-all"
                style={{
                  background: preset === p.id ? "var(--accent-dim)" : "var(--surface-2)",
                  color: preset === p.id ? "var(--accent)" : "var(--text-dim)",
                  border: preset === p.id ? "1px solid rgba(0,229,255,0.25)" : "1px solid transparent",
                }}
              >
                <div className="text-sm font-medium">{p.label}</div>
                <div className="text-[10px] mt-0.5 opacity-60">{p.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Hikvision / Dahua form */}
        {preset !== "custom" && (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <div className="col-span-2">
                <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>IP / DDNS адрес камеры</label>
                <input
                  value={ip}
                  onChange={(e) => { setIp(e.target.value); setTestResult(null); }}
                  placeholder="192.168.1.64 или mysalon.ddns.net"
                  className="w-full glass-input px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Порт</label>
                <input
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder="554"
                  className="w-full glass-input px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Логин</label>
                <input
                  value={user}
                  onChange={(e) => { setUser(e.target.value); setTestResult(null); }}
                  placeholder="admin"
                  className="w-full glass-input px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Пароль</label>
                <input
                  type="password"
                  value={pass}
                  onChange={(e) => { setPass(e.target.value); setTestResult(null); }}
                  placeholder="••••••••"
                  className="w-full glass-input px-3 py-2 text-sm"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Канал</label>
                <select
                  value={channel}
                  onChange={(e) => setChannel(parseInt(e.target.value))}
                  className="w-full glass-input px-3 py-2 text-sm"
                  style={{ color: "var(--text)", background: "var(--surface-2)" }}
                >
                  {[1, 2, 3, 4, 5, 6, 7, 8].map((ch) => (
                    <option key={ch} value={ch}>Канал {ch}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Поток</label>
                <select
                  value={stream}
                  onChange={(e) => setStream(e.target.value as "main" | "sub")}
                  className="w-full glass-input px-3 py-2 text-sm"
                  style={{ color: "var(--text)", background: "var(--surface-2)" }}
                >
                  <option value="sub">Доп. поток (рек.)</option>
                  <option value="main">Основной поток</option>
                </select>
              </div>
            </div>

            {/* Generated URL preview */}
            {ip && (
              <div className="glass-card-sm p-2.5 rounded-xl">
                <div className="text-[10px] font-mono break-all" style={{ color: "var(--accent)", opacity: 0.7 }}>
                  {rtspUrl.replace(/:([^@]+)@/, ":****@")}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Custom URL input */}
        {preset === "custom" && (
          <div>
            <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>RTSP URL</label>
            <input
              value={customUrl}
              onChange={(e) => { setCustomUrl(e.target.value); setTestResult(null); }}
              placeholder="rtsp://admin:password@192.168.1.64:554/live"
              className="w-full glass-input px-3 py-2 text-sm font-mono"
            />
          </div>
        )}

        {/* Camera name & ID */}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Название</label>
            <input
              value={camName}
              onChange={(e) => setCamName(e.target.value)}
              placeholder="Холл / Вход / Ресепшн"
              className="w-full glass-input px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="text-xs block mb-1" style={{ color: "var(--text-dim)" }}>Локация</label>
            <input
              value={locationId}
              onChange={(e) => setLocationId(e.target.value)}
              placeholder="salon-1"
              className="w-full glass-input px-3 py-2 text-sm"
            />
          </div>
        </div>

        {/* Test button */}
        <button
          onClick={handleTest}
          disabled={!canTest || testing}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-40"
          style={{
            background: testResult?.ok ? "rgba(74,222,128,0.12)" : "var(--surface-2)",
            color: testResult?.ok ? "var(--green)" : "var(--text)",
            border: testResult?.ok ? "1px solid rgba(74,222,128,0.3)" : testResult && !testResult.ok ? "1px solid rgba(255,59,92,0.3)" : "1px solid transparent",
          }}
        >
          {testing ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Проверка подключения...
            </>
          ) : testResult?.ok ? (
            <>
              <CheckCircle2 size={16} />
              Подключение OK — {testResult.width}x{testResult.height} @ {testResult.fps} fps
            </>
          ) : testResult && !testResult.ok ? (
            <>
              <WifiOff size={16} style={{ color: "var(--red)" }} />
              <span style={{ color: "var(--red)" }}>{testResult.error}</span>
            </>
          ) : (
            <>
              <Wifi size={16} />
              Проверить подключение
            </>
          )}
        </button>

        {/* Hikvision instructions */}
        {preset === "hikvision" && !testResult?.ok && (
          <div className="glass-card-sm p-3 space-y-3 rounded-xl">
            <p className="text-[11px] font-medium" style={{ color: "var(--text)" }}>
              Подключение Hikvision / Hik-Connect
            </p>

            <div className="space-y-2">
              <p className="text-[10px] font-medium" style={{ color: "var(--accent)" }}>Вариант 1: Sentinel в одной сети с камерой (рекомендуется)</p>
              <ol className="text-[10px] space-y-1 list-decimal list-inside" style={{ color: "var(--text-dim)" }}>
                <li>Откройте <b>Hik-Connect</b> → камера → ⚙ Настройки → Информация</li>
                <li>Или скачайте <b>SADP Tool</b> — найдёт все камеры в сети</li>
                <li>Введите IP (обычно <code className="px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>192.168.x.x</code>)</li>
                <li>Логин: <code className="px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>admin</code>, пароль — ваш</li>
              </ol>
            </div>

            <div className="space-y-2">
              <p className="text-[10px] font-medium" style={{ color: "var(--accent)" }}>Вариант 2: Удалённый доступ (через интернет)</p>
              <ol className="text-[10px] space-y-1 list-decimal list-inside" style={{ color: "var(--text-dim)" }}>
                <li>На роутере салона настройте <b>проброс порта 554</b> (TCP) на IP камеры</li>
                <li>Используйте внешний IP роутера или <b>DDNS</b> (Hik-Connect → Настройки сети → DDNS)</li>
                <li>В поле IP введите ваш DDNS адрес или внешний IP</li>
                <li>Пример: <code className="px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>mysalon.hik-online.com</code> или <code className="px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>85.192.x.x</code></li>
              </ol>
            </div>

            <div className="space-y-1 pt-1" style={{ borderTop: "1px solid var(--glass-border)" }}>
              <p className="text-[10px]" style={{ color: "var(--text-dim)" }}>
                Рекомендуем <b>доп. поток (sub)</b> — меньше трафика, для ИИ-анализа достаточно.
              </p>
              <p className="text-[10px]" style={{ color: "var(--text-dim)" }}>
                Для 120+ салонов рекомендуем установить <b>Edge Agent</b> в каждом салоне — он обрабатывает видео локально и отправляет только события на сервер.
              </p>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-1">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-xl text-sm glass-card-sm transition-colors hover:border-[var(--text-dim)]"
            style={{ color: "var(--text-dim)" }}
          >
            Отмена
          </button>
          <button
            onClick={handleAdd}
            disabled={!canTest || submitting}
            className="flex-1 py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-40"
            style={{ background: "var(--accent)", color: "#06080f" }}
          >
            {submitting ? "Подключение..." : "Подключить камеру"}
          </button>
        </div>
        </>}
      </div>
    </div>
  );
}

function HikConnectImport({ onImported }: { onImported: (cam: { id: string; name: string; url: string; location_id: string; enabled: boolean; running: boolean }) => void }) {
  const [cloudCameras, setCloudCameras] = useState<HikCamera[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [importing, setImporting] = useState<string | null>(null);

  async function loadCameras() {
    setLoading(true);
    setError("");
    try {
      const data = await hikconnectApi.listCameras();
      setCloudCameras(data.cameras);
      if (data.cameras.length === 0) {
        setError("Камеры не найдены. Подключите аккаунт Hik-Connect через админ-панель.");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Ошибка загрузки";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function importCamera(cam: HikCamera) {
    setImporting(`${cam.device_serial}-${cam.channel_no}`);
    try {
      const result = await hikconnectApi.importCamera({
        device_serial: cam.device_serial,
        channel_no: cam.channel_no,
        name: cam.name,
      });
      toast.success(`Камера «${result.name}» подключена через облако!`);
      onImported(result);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Ошибка импорта";
      toast.error(msg);
    } finally {
      setImporting(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="glass-card-sm p-3 rounded-xl">
        <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
          Камеры из вашего аккаунта <b>Hik-Connect</b> (тот же логин что в приложении на телефоне).
          Подключение через облако — не нужен проброс портов.
        </p>
      </div>

      {cloudCameras.length === 0 && !loading && (
        <button
          onClick={loadCameras}
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium transition-all"
          style={{ background: "var(--accent-dim)", color: "var(--accent)", border: "1px solid rgba(0,229,255,0.2)" }}
        >
          <Cloud size={16} />
          Загрузить камеры из Hik-Connect
        </button>
      )}

      {loading && (
        <div className="flex items-center justify-center gap-2 py-6" style={{ color: "var(--text-dim)" }}>
          <Loader2 size={18} className="animate-spin" />
          <span className="text-sm">Загрузка камер из облака...</span>
        </div>
      )}

      {error && (
        <div className="glass-card-sm p-3 rounded-xl text-[11px]" style={{ color: "var(--red)", border: "1px solid rgba(255,59,92,0.2)" }}>
          {error}
        </div>
      )}

      {cloudCameras.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium" style={{ color: "var(--text-dim)" }}>
            Найдено камер: {cloudCameras.length}
          </div>
          {cloudCameras.map((cam) => {
            const camKey = `${cam.device_serial}-${cam.channel_no}`;
            return (
              <div
                key={camKey}
                className="flex items-center justify-between gap-3 p-3 rounded-xl glass-card-sm"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <div
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{
                        background: cam.status === "online" ? "var(--green)" : "var(--red)",
                        boxShadow: cam.status === "online" ? "0 0 6px var(--green)" : "none",
                      }}
                    />
                    <span className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>
                      {cam.name}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-dim)" }}>
                      {cam.device_serial}
                    </span>
                    <span className="text-[10px]" style={{ color: "var(--accent)" }}>
                      CH{cam.channel_no}
                    </span>
                  </div>
                </div>
                <button
                  onClick={() => importCamera(cam)}
                  disabled={importing === camKey || cam.status !== "online"}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all disabled:opacity-40 flex-shrink-0"
                  style={{ background: "var(--accent)", color: "#06080f" }}
                >
                  {importing === camKey ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Download size={12} />
                  )}
                  {cam.status !== "online" ? "Оффлайн" : importing === camKey ? "..." : "Подключить"}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
