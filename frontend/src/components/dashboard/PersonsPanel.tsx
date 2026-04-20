"use client";

import { useEffect, useState } from "react";
import { personsApi, type Person } from "@/lib/api";
import { Users } from "lucide-react";
import toast from "react-hot-toast";

const CATEGORIES = ["all", "new", "regular", "vip", "staff"] as const;
type Cat = (typeof CATEGORIES)[number];

export function PersonsPanel() {
  const [persons, setPersons] = useState<Person[]>([]);
  const [cat, setCat] = useState<Cat>("all");
  const [loading, setLoading] = useState(true);
  const [enrollOpen, setEnrollOpen] = useState(false);

  async function load(category: Cat) {
    setLoading(true);
    try {
      const data = await personsApi.list(category === "all" ? undefined : category);
      setPersons(data);
    } catch {
      toast.error("Ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(cat);
  }, [cat]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--text-dim)" }}>
          База людей
        </span>

        <div className="flex gap-1 ml-2 flex-wrap">
          {CATEGORIES.map((c) => (
            <button
              key={c}
              onClick={() => setCat(c)}
              className="px-3 py-1.5 rounded-xl text-xs transition-all min-h-[32px]"
              style={{
                background: cat === c ? "var(--accent-dim)" : "transparent",
                color: cat === c ? "var(--accent)" : "var(--text-dim)",
                border: cat === c ? "1px solid rgba(0,229,255,0.3)" : "1px solid var(--border)",
              }}
            >
              {c === "all" ? "Все" : c.toUpperCase()}
            </button>
          ))}
        </div>

        <button
          onClick={() => setEnrollOpen(true)}
          className="ml-auto px-4 py-1.5 rounded-xl text-xs font-medium transition-all"
          style={{ background: "var(--accent)", color: "#06080f" }}
        >
          + Добавить профиль
        </button>
      </div>

      {/* Loading skeleton */}
      {loading && (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="skeleton h-14 w-full" />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && persons.length === 0 && (
        <div className="glass-card py-12 text-center">
          <Users size={24} className="mx-auto mb-2 opacity-30" style={{ color: "var(--text-dim)" }} />
          <p className="text-xs" style={{ color: "var(--text-dim)" }}>Нет данных</p>
        </div>
      )}

      {/* Mobile: Card view */}
      {!loading && persons.length > 0 && (
        <div className="sm:hidden space-y-2">
          {persons.map((p) => (
            <div key={p.id} className="glass-card p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{p.name}</div>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] badge-${p.category}`}>
                    {p.category}
                  </span>
                  <span className="text-xs font-mono" style={{ color: "var(--accent)" }}>
                    {p.visit_count} визитов
                  </span>
                </div>
              </div>
              <div className="text-right text-[11px] shrink-0" style={{ color: "var(--text-dim)" }}>
                {p.email ?? p.phone ?? ""}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Desktop: Table view */}
      {!loading && persons.length > 0 && (
        <div className="hidden sm:block glass-card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                {["Имя", "Категория", "Визитов", "Email / Телефон", "Заметки"].map((h) => (
                  <th
                    key={h}
                    className="text-left px-4 py-3 text-xs font-medium"
                    style={{ color: "var(--text-dim)" }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {persons.map((p) => (
                <tr
                  key={p.id}
                  style={{ borderBottom: "1px solid var(--border)" }}
                  className="hover:bg-[rgba(0,229,255,0.02)] transition-colors"
                >
                  <td className="px-4 py-3 font-medium">{p.name}</td>
                  <td className="px-4 py-3">
                    <span className={`px-2 py-0.5 rounded text-[11px] badge-${p.category}`}>
                      {p.category}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono" style={{ color: "var(--accent)" }}>
                    {p.visit_count}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: "var(--text-dim)" }}>
                    {p.email ?? p.phone ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: "var(--text-dim)" }}>
                    {p.notes ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Enroll modal */}
      {enrollOpen && <EnrollModal onClose={() => { setEnrollOpen(false); load(cat); }} />}
    </div>
  );
}

function EnrollModal({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [category, setCategory] = useState("regular");
  const [photo, setPhoto] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit() {
    if (!name || !photo) {
      toast.error("Укажите имя и фото");
      return;
    }
    setLoading(true);
    const form = new FormData();
    form.append("name", name);
    form.append("category", category);
    form.append("photo", photo);

    try {
      await personsApi.enroll(form);
      toast.success(`${name} добавлен(а) в базу`);
      onClose();
    } catch {
      toast.error("Ошибка добавления");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 modal-backdrop" onClick={onClose}>
      <div className="w-full max-w-md glass-card p-6 space-y-4 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-semibold">Добавить профиль</h3>

        <div>
          <label htmlFor="person-name" className="sr-only">Имя</label>
          <input
            id="person-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Имя"
            className="w-full glass-input px-3 py-2.5 text-sm"
          />
        </div>

        <div>
          <label htmlFor="person-category" className="sr-only">Категория</label>
          <select
            id="person-category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full glass-input px-3 py-2.5 text-sm"
          >
            <option value="regular">Regular</option>
            <option value="vip">VIP</option>
            <option value="staff">Staff</option>
          </select>
        </div>

        <div
          className="border-2 border-dashed rounded-xl p-6 text-center cursor-pointer text-xs transition-colors"
          style={{
            borderColor: photo ? "var(--accent)" : "var(--border)",
            color: "var(--text-dim)",
            background: photo ? "var(--accent-dim)" : "transparent",
          }}
          onClick={() => document.getElementById("photo-input")?.click()}
        >
          {photo ? photo.name : "Нажмите для загрузки фото"}
          <input
            id="photo-input"
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="flex gap-3 pt-2">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-xl text-sm glass-card-sm transition-colors hover:border-[var(--text-dim)]"
            style={{ color: "var(--text-dim)" }}
          >
            Отмена
          </button>
          <button
            onClick={submit}
            disabled={loading}
            className="flex-1 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50 transition-all"
            style={{ background: "var(--accent)", color: "#06080f" }}
          >
            {loading ? "Сохранение..." : "Добавить"}
          </button>
        </div>
      </div>
    </div>
  );
}
