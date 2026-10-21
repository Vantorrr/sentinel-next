"use client";

import { useState, useEffect, useCallback, type FormEvent } from "react";
import { zonesApi, camerasApi, type Zone, type Camera } from "@/lib/api";
import {
  AlertTriangle,
  Clock,
  MapPin,
  Plus,
  Shield,
  Trash2,
  UserCheck,
  X,
} from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";

const ZONE_TYPES = [
  { value: "reception", label: "Ресепшн", desc: "Зона администратора" },
  { value: "waiting", label: "Зал ожидания", desc: "Клиенты ждут обслуживания" },
  { value: "service", label: "Зона обслуживания", desc: "Рабочие места мастеров" },
  { value: "entrance", label: "Вход", desc: "Входная зона" },
  { value: "staff_only", label: "Служебная", desc: "Только для персонала" },
  { value: "custom", label: "Другая", desc: "Пользовательская зона" },
];

export function ZonesPanel() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [z, c] = await Promise.all([zonesApi.list(), camerasApi.list()]);
      setZones(z);
      setCameras(c);
      setError("");
    } catch {
      setError("Ошибка загрузки зон");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const handleDelete = async (id: string) => {
    try {
      await zonesApi.delete(id);
      reload();
    } catch {
      setError("Ошибка удаления зоны");
    }
  };

  const grouped = cameras.map((cam) => ({
    camera: cam,
    zones: zones.filter((z) => z.camera_id === cam.id),
  }));

  if (loading) {
    return (
      <div className="p-4 lg:p-6 space-y-4">
        <div className="skeleton h-8 w-48 rounded-lg" />
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-24 rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-4 lg:p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold font-display" style={{ color: "var(--text)" }}>
            Зоны · Красная книга
          </h2>
          <p className="text-xs mt-1" style={{ color: "var(--text-dim)" }}>
            Стандарты Вай Тай: встреча Гостя, ресепшен, ожидание/чай + Telegram-замечания
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium transition-all"
            style={{ background: "var(--accent)", color: "#061018" }}
          >
            <Plus size={16} />
            Добавить зону
          </button>
        </div>
      </div>

      {cameras.length > 0 && (
        <div className="glass-card p-4 flex flex-col sm:flex-row sm:items-center gap-3 justify-between">
          <div>
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              Пресет «Вай Тай · Красная книга»
            </p>
            <p className="text-xs mt-1" style={{ color: "var(--text-dim)" }}>
              Вход (45с) · Ресепшен staff (3 мин) · Ожидание/чай (90с). Потом подправьте рамки под кадр.
            </p>
          </div>
          <RedBookPresetButtons cameras={cameras} onDone={reload} onError={setError} />
        </div>
      )}

      {error && (
        <div className="glass-card px-4 py-3 text-sm flex items-center gap-2" style={{ color: "var(--red)" }}>
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {zones.length === 0 && (
        <div
          className="glass-card p-8 flex flex-col items-center gap-4 text-center"
        >
          <MapPin size={40} style={{ color: "var(--text-dim)", opacity: 0.3 }} />
          <div>
            <p className="font-medium" style={{ color: "var(--text)" }}>
              Зоны не настроены
            </p>
            <p className="text-sm mt-1" style={{ color: "var(--text-dim)" }}>
              Добавьте зону для камеры, чтобы получать алерты о присутствии персонала и клиентов
            </p>
          </div>
        </div>
      )}

      {grouped.map(({ camera, zones: camZones }) => (
        <div key={camera.id}>
          {camZones.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-mono flex items-center gap-2" style={{ color: "var(--text-dim)" }}>
                <MapPin size={14} />
                {camera.name || camera.id}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {camZones.map((zone) => (
                  <ZoneCard key={zone.id} zone={zone} onDelete={handleDelete} />
                ))}
              </div>
            </div>
          )}
        </div>
      ))}

      {showCreate && (
        <CreateZoneModal
          cameras={cameras}
          onClose={() => setShowCreate(false)}
          onCreated={reload}
        />
      )}
    </div>
  );
}

function ZoneCard({ zone, onDelete }: { zone: Zone; onDelete: (id: string) => void }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const typeInfo = ZONE_TYPES.find((t) => t.value === zone.zone_type) ?? ZONE_TYPES[5];

  return (
    <div className="glass-card p-4 space-y-3">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-medium text-sm" style={{ color: "var(--text)" }}>
            {zone.name}
          </p>
          <p className="text-[10px] font-mono mt-0.5" style={{ color: "var(--text-dim)" }}>
            {typeInfo.label}
          </p>
        </div>
        <Dialog.Root open={confirmDelete} onOpenChange={setConfirmDelete}>
          <Dialog.Trigger asChild>
            <button
              aria-label="Удалить зону"
              className="p-1.5 rounded-lg transition-colors hover:bg-[var(--surface-2)]"
              style={{ color: "var(--text-dim)" }}
            >
              <Trash2 size={14} />
            </button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
            <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-80 glass-card p-6 rounded-2xl space-y-4">
              <Dialog.Title className="font-bold" style={{ color: "var(--text)" }}>
                Удалить зону?
              </Dialog.Title>
              <p className="text-sm" style={{ color: "var(--text-dim)" }}>
                Зона «{zone.name}» будет удалена. Отменить нельзя.
              </p>
              <div className="flex gap-2 justify-end">
                <Dialog.Close asChild>
                  <button className="px-4 py-2 rounded-xl text-sm glass-card-sm" style={{ color: "var(--text-dim)" }}>
                    Отмена
                  </button>
                </Dialog.Close>
                <button
                  onClick={() => { onDelete(zone.id); setConfirmDelete(false); }}
                  className="px-4 py-2 rounded-xl text-sm font-medium"
                  style={{ background: "var(--red)", color: "#fff" }}
                >
                  Удалить
                </button>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>

      <div className="flex flex-wrap gap-2">
        {zone.staff_required && (
          <span
            className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full"
            style={{ background: "rgba(0,229,255,0.1)", color: "var(--accent)" }}
          >
            <UserCheck size={10} />
            Персонал обязателен
          </span>
        )}
        <span
          className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full"
          style={{ background: "rgba(255,255,255,0.05)", color: "var(--text-dim)" }}
        >
          <Clock size={10} />
          Макс. отсутствие: {Math.round(zone.max_absence_seconds / 60)} мин
        </span>
        <span
          className="flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded-full"
          style={{ background: "rgba(255,255,255,0.05)", color: "var(--text-dim)" }}
        >
          <Shield size={10} />
          Макс. ожидание: {Math.round(zone.max_wait_seconds / 60)} мин
        </span>
      </div>

      <div className="text-[10px] font-mono" style={{ color: "var(--text-dim)", opacity: 0.5 }}>
        {zone.polygon.length} точек | {zone.is_active ? "активна" : "неактивна"}
      </div>
    </div>
  );
}

function CreateZoneModal({
  cameras,
  onClose,
  onCreated,
}: {
  cameras: Camera[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const [cameraId, setCameraId] = useState(cameras[0]?.id ?? "");
  const [name, setName] = useState("");
  const [zoneType, setZoneType] = useState("reception");
  const [polygonStr, setPolygonStr] = useState("[[0,0],[640,0],[640,480],[0,480]]");
  const [staffRequired, setStaffRequired] = useState(true);
  const [maxAbsence, setMaxAbsence] = useState(3); // мин — Красная книга ресепшен
  const [maxWait, setMaxWait] = useState(1); // мин — гл.3 встреча Гостя
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    let polygon: number[][];
    try {
      polygon = JSON.parse(polygonStr);
      if (!Array.isArray(polygon) || polygon.length < 3) throw new Error("min 3 points");
    } catch {
      setError("Невалидный полигон — нужен JSON массив [[x,y], ...] минимум 3 точки");
      return;
    }

    setSubmitting(true);
    try {
      await zonesApi.create(cameraId, {
        name,
        zone_type: zoneType,
        polygon,
        staff_required: staffRequired,
        max_absence_seconds: maxAbsence * 60,
        max_wait_seconds: maxWait * 60,
      });
      onCreated();
      onClose();
    } catch {
      setError("Ошибка создания зоны");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(v) => { if (!v) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60" />
        <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md glass-card p-6 rounded-2xl max-h-[85vh] overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <Dialog.Title className="font-bold text-lg" style={{ color: "var(--text)" }}>
              Новая зона
            </Dialog.Title>
            <Dialog.Close asChild>
              <button aria-label="Закрыть" className="p-1" style={{ color: "var(--text-dim)" }}>
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-dim)" }}>
                Камера
              </label>
              <select
                value={cameraId}
                onChange={(e) => setCameraId(e.target.value)}
                className="glass-input w-full px-3 py-2 rounded-xl text-sm"
                style={{ color: "var(--text)", background: "var(--surface-2)" }}
              >
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name || c.id}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-dim)" }}>
                Название зоны
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Ресепшн"
                required
                className="glass-input w-full px-3 py-2 rounded-xl text-sm"
              />
            </div>

            <div>
              <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-dim)" }}>
                Тип зоны
              </label>
              <select
                value={zoneType}
                onChange={(e) => setZoneType(e.target.value)}
                className="glass-input w-full px-3 py-2 rounded-xl text-sm"
                style={{ color: "var(--text)", background: "var(--surface-2)" }}
              >
                {ZONE_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label} — {t.desc}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-dim)" }}>
                Полигон (координаты в пикселях)
              </label>
              <textarea
                value={polygonStr}
                onChange={(e) => setPolygonStr(e.target.value)}
                rows={3}
                className="glass-input w-full px-3 py-2 rounded-xl text-sm font-mono"
                placeholder="[[0,0],[640,0],[640,480],[0,480]]"
              />
              <p className="text-[10px] mt-1" style={{ color: "var(--text-dim)" }}>
                JSON массив точек [[x,y], ...]. Минимум 3 точки.
              </p>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="staff-req"
                checked={staffRequired}
                onChange={(e) => setStaffRequired(e.target.checked)}
                className="rounded"
              />
              <label htmlFor="staff-req" className="text-sm" style={{ color: "var(--text)" }}>
                Персонал обязателен в этой зоне
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-dim)" }}>
                  Макс. отсутствие (мин)
                </label>
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={maxAbsence}
                  onChange={(e) => setMaxAbsence(parseInt(e.target.value) || 5)}
                  className="glass-input w-full px-3 py-2 rounded-xl text-sm"
                />
              </div>
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: "var(--text-dim)" }}>
                  Макс. ожидание клиента (мин)
                </label>
                <input
                  type="number"
                  min={1}
                  max={30}
                  value={maxWait}
                  onChange={(e) => setMaxWait(parseInt(e.target.value) || 2)}
                  className="glass-input w-full px-3 py-2 rounded-xl text-sm"
                />
              </div>
            </div>

            {error && (
              <p className="text-sm flex items-center gap-1.5" style={{ color: "var(--red)" }}>
                <AlertTriangle size={14} />
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={submitting || !name || !cameraId}
              className="w-full py-2.5 rounded-xl text-sm font-medium transition-all disabled:opacity-50"
              style={{ background: "var(--accent)", color: "#061018" }}
            >
              {submitting ? "Создание..." : "Создать зону"}
            </button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function RedBookPresetButtons({
  cameras,
  onDone,
  onError,
}: {
  cameras: Camera[];
  onDone: () => void;
  onError: (msg: string) => void;
}) {
  const [cameraId, setCameraId] = useState(cameras[0]?.id ?? "");
  const [busy, setBusy] = useState(false);

  const apply = async (replace: boolean) => {
    if (!cameraId) return;
    setBusy(true);
    onError("");
    try {
      const res = await zonesApi.applyRedbookPresets(cameraId, {
        replace_existing: replace,
        frame_width: 1920,
        frame_height: 1080,
      });
      onDone();
      if (res.note) {
        // soft note via error slot is ok as info — keep clean
      }
    } catch (err: unknown) {
      onError(err instanceof Error ? err.message : "Не удалось применить пресет Красной книги");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
      <select
        value={cameraId}
        onChange={(e) => setCameraId(e.target.value)}
        className="glass-input px-3 py-2 text-xs min-w-[160px]"
      >
        {cameras.map((c) => (
          <option key={c.id} value={c.id}>{c.name || c.id}</option>
        ))}
      </select>
      <button
        disabled={busy || !cameraId}
        onClick={() => apply(false)}
        className="btn-accent px-3 py-2 text-xs disabled:opacity-40"
      >
        {busy ? "..." : "Применить пресет"}
      </button>
      <button
        disabled={busy || !cameraId}
        onClick={() => apply(true)}
        className="glass-card-sm px-3 py-2 text-xs disabled:opacity-40"
        style={{ color: "var(--text-dim)" }}
        title="Удалит старые зоны этой камеры"
      >
        Заменить зоны
      </button>
    </div>
  );
}
