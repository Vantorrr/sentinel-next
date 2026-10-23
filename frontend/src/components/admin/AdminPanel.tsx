"use client";

import { useState, useEffect, useCallback, type FormEvent } from "react";
import { adminApi, hikconnectApi, type TenantSummary, type TenantDetail, type GlobalStats } from "@/lib/api";
import { AlertTriangle, ChevronDown, Cloud, Copy, Key, Plus, RefreshCw, Send, Trash2, X } from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";

export function AdminPanel() {
  const [stats, setStats] = useState<GlobalStats | null>(null);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [selected, setSelected] = useState<TenantDetail | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [s, t] = await Promise.all([adminApi.stats(), adminApi.listTenants()]);
      setStats(s);
      setTenants(t);
      setError("");
    } catch {
      setError("Ошибка загрузки данных");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  return (
    <div className="flex-1 overflow-y-auto p-4 lg:p-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold">Управление платформой</h2>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 rounded-xl px-4 py-2 text-sm font-medium transition-all"
          style={{ background: "var(--accent)", color: "#06080f" }}
        >
          <Plus size={14} />
          Новый салон
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm" style={{ background: "rgba(255,59,92,0.08)", border: "1px solid rgba(255,59,92,0.2)", color: "var(--red)" }}>
          <AlertTriangle size={14} />
          {error}
        </div>
      )}

      {/* Stats */}
      {loading && !stats && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          {[...Array(5)].map((_, i) => <div key={i} className="skeleton h-20" />)}
        </div>
      )}
      {stats && <StatsCards stats={stats} />}

      {/* Setup guide */}
      <SetupGuide />

      {/* Tenant list */}
      {loading && tenants.length === 0 && (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="skeleton h-16" />)}
        </div>
      )}
      <div className="space-y-2">
        {tenants.map((t) => (
          <TenantRow
            key={t.id}
            tenant={t}
            onSelect={async () => {
              const detail = await adminApi.getTenant(t.id);
              setSelected(detail);
            }}
          />
        ))}
      </div>

      {/* Selected tenant detail */}
      {selected && (
        <TenantDetailDialog
          tenant={selected}
          onClose={() => setSelected(null)}
          onRefresh={reload}
        />
      )}

      {/* Create dialog */}
      {showCreate && (
        <CreateTenantDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); reload(); }}
        />
      )}
    </div>
  );
}

function StatsCards({ stats }: { stats: GlobalStats }) {
  const cards = [
    { label: "Салоны", value: `${stats.active_tenants}/${stats.total_tenants}`, sub: "активных" },
    { label: "Пользователи", value: stats.total_users, sub: "" },
    { label: "Агенты", value: `${stats.agents_online}/${stats.total_agents}`, sub: "онлайн" },
    { label: "Визиты", value: stats.total_visits_today, sub: "сегодня" },
    { label: "Алерты", value: stats.total_alerts_today, sub: "сегодня" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 lg:gap-3">
      {cards.map((c) => (
        <div key={c.label} className="glass-card p-4">
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>{c.label}</div>
          <div className="text-2xl font-bold mt-1" style={{ color: "var(--text)" }}>{c.value}</div>
          {c.sub && <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{c.sub}</div>}
        </div>
      ))}
    </div>
  );
}

function TenantRow({ tenant, onSelect }: { tenant: TenantSummary; onSelect: () => void }) {
  const planColor: Record<string, string> = {
    free: "#888",
    pro: "#00d4ff",
    enterprise: "#c084fc",
  };

  return (
    <button
      onClick={onSelect}
      className="w-full flex items-center gap-3 lg:gap-4 glass-card p-3 lg:p-4 text-left hover:border-[var(--accent)] transition-all"
    >
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm truncate">{tenant.name}</div>
        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{tenant.slug}</div>
      </div>
      <span
        className="hidden sm:inline-block rounded-full px-2 py-0.5 text-xs font-mono uppercase"
        style={{ color: planColor[tenant.plan] || "#888", border: `1px solid ${planColor[tenant.plan] || "#888"}40` }}
      >
        {tenant.plan}
      </span>
      <div className="text-right text-[11px]" style={{ color: "var(--text-muted)" }}>
        <div>{tenant.users_count} users</div>
        <div>{tenant.agents_count} agents</div>
      </div>
      <div
        className="w-2 h-2 rounded-full shrink-0"
        style={{ background: tenant.is_active ? "var(--green)" : "var(--red)" }}
      />
    </button>
  );
}

function TenantDetailDialog({
  tenant,
  onClose,
  onRefresh,
}: {
  tenant: TenantDetail;
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [showAddUser, setShowAddUser] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const copyKey = () => {
    navigator.clipboard.writeText(tenant.api_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRegenerate = async () => {
    const res = await adminApi.regenerateKey(tenant.id);
    setConfirmRegen(false);
    tenant.api_key = res.api_key;
    onRefresh();
  };

  const handleDeleteTenant = async () => {
    await adminApi.deleteTenant(tenant.id);
    onClose();
    onRefresh();
  };

  const handleDeleteUser = async (userId: string) => {
    await adminApi.deleteUser(tenant.id, userId);
    onRefresh();
  };

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 modal-backdrop" />
        <Dialog.Content className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[95vw] max-w-2xl max-h-[85vh] overflow-y-auto glass-card p-6 shadow-2xl space-y-4">
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-lg font-bold">{tenant.name}</Dialog.Title>
            <Dialog.Close asChild>
              <button className="p-1.5 rounded-lg hover:bg-[var(--surface-2)] transition-colors" style={{ color: "var(--text-muted)" }} aria-label="Закрыть">
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>

          {/* API Key */}
          <div className="glass-card-sm p-3">
            <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>API Key</div>
            <div className="flex items-center gap-2 flex-wrap">
              <code className="flex-1 font-mono text-sm break-all min-w-0" style={{ color: "var(--accent)" }}>{tenant.api_key}</code>
              <button onClick={copyKey} className="flex items-center gap-1 text-xs shrink-0 p-1.5 rounded-lg hover:bg-[var(--surface-2)] transition-colors" style={{ color: "var(--text-muted)" }}>
                <Copy size={12} />
                {copied ? "Copied!" : "Copy"}
              </button>
              <button onClick={() => setConfirmRegen(true)} className="flex items-center gap-1 text-xs shrink-0 p-1.5 rounded-lg hover:bg-[rgba(255,59,92,0.1)] transition-colors" style={{ color: "var(--red)" }}>
                <Key size={12} />
                Regen
              </button>
            </div>
          </div>

          {/* Telegram Setup */}
          <TelegramSetup tenantApiKey={tenant.api_key} />

          {/* Confirm regeneration */}
          {confirmRegen && (
            <div className="glass-card-sm p-3 flex items-center gap-3" style={{ borderColor: "rgba(255,59,92,0.3)" }}>
              <AlertTriangle size={16} style={{ color: "var(--red)" }} className="shrink-0" />
              <p className="text-xs flex-1" style={{ color: "var(--text)" }}>
                Перегенерировать ключ? Все агенты потеряют доступ!
              </p>
              <button onClick={handleRegenerate} className="text-xs px-3 py-1 rounded-lg font-medium" style={{ background: "rgba(255,59,92,0.15)", color: "var(--red)" }}>
                Да
              </button>
              <button onClick={() => setConfirmRegen(false)} className="text-xs px-3 py-1 rounded-lg" style={{ color: "var(--text-muted)" }}>
                Нет
              </button>
            </div>
          )}

          {/* Delete tenant */}
          {!confirmDelete ? (
            <button
              onClick={() => setConfirmDelete(true)}
              className="flex items-center gap-1.5 text-xs transition-colors p-1.5 rounded-lg hover:bg-[rgba(255,59,92,0.1)]"
              style={{ color: "var(--red)" }}
            >
              <Trash2 size={12} />
              Удалить салон
            </button>
          ) : (
            <div className="glass-card-sm p-3 flex items-center gap-3" style={{ borderColor: "rgba(255,59,92,0.3)" }}>
              <AlertTriangle size={16} style={{ color: "var(--red)" }} className="shrink-0" />
              <p className="text-xs flex-1" style={{ color: "var(--text)" }}>
                Удалить {tenant.name}? Все данные (камеры, визиты, зоны) будут удалены!
              </p>
              <button onClick={handleDeleteTenant} className="text-xs px-3 py-1 rounded-lg font-medium" style={{ background: "rgba(255,59,92,0.15)", color: "var(--red)" }}>
                Да
              </button>
              <button onClick={() => setConfirmDelete(false)} className="text-xs px-3 py-1 rounded-lg" style={{ color: "var(--text-muted)" }}>
                Нет
              </button>
            </div>
          )}

          {/* Agents */}
          <div>
            <h4 className="text-sm font-medium mb-2">Агенты ({tenant.agents.length})</h4>
            {tenant.agents.length === 0 ? (
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>Нет подключенных агентов</p>
            ) : (
              <div className="space-y-1">
                {tenant.agents.map((a) => (
                  <div key={a.id} className="flex items-center gap-3 glass-card-sm p-2.5 text-xs">
                    <div className="w-2 h-2 rounded-full shrink-0" style={{ background: a.status === "online" ? "var(--green)" : "var(--red)" }} />
                    <span className="truncate">{a.agent_name || a.id}</span>
                    <span className="hidden sm:inline truncate" style={{ color: "var(--text-muted)" }}>{a.hostname}</span>
                    <span className="ml-auto shrink-0 font-mono" style={{ color: "var(--text-muted)" }}>{a.cameras_count} cam</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Users */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-sm font-medium">Пользователи ({tenant.users.length})</h4>
              <button onClick={() => setShowAddUser(true)} className="text-xs flex items-center gap-1 transition-colors" style={{ color: "var(--accent)" }}>
                <Plus size={12} />
                Добавить
              </button>
            </div>
            <div className="space-y-1">
              {tenant.users.map((u) => (
                <div key={u.id} className="flex items-center gap-3 glass-card-sm p-2.5 text-xs flex-wrap sm:flex-nowrap">
                  <span className="truncate">{u.email}</span>
                  <span className="hidden sm:inline" style={{ color: "var(--text-muted)" }}>{u.name}</span>
                  <span className="rounded-lg px-2 py-0.5 text-[10px] uppercase font-mono glass-card-sm">
                    {u.role}
                  </span>
                  <button
                    onClick={() => handleDeleteUser(u.id)}
                    className="ml-auto p-1 rounded-lg hover:bg-[rgba(255,59,92,0.1)] transition-colors shrink-0"
                    style={{ color: "var(--text-muted)" }}
                    title="Удалить пользователя"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          </div>

          {showAddUser && (
            <AddUserForm
              tenantId={tenant.id}
              onClose={() => setShowAddUser(false)}
              onCreated={() => { setShowAddUser(false); onRefresh(); }}
            />
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function CreateTenantDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [plan, setPlan] = useState("pro");
  const [maxCams, setMaxCams] = useState(8);
  const [contactEmail, setContactEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ api_key: string } | null>(null);
  const [error, setError] = useState("");

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const res = await adminApi.createTenant({
        name,
        slug: slug || name.toLowerCase().replace(/\s+/g, "-"),
        plan,
        max_cameras: maxCams,
        contact_email: contactEmail || undefined,
      });
      setResult(res);
    } catch {
      setError("Ошибка создания салона");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 modal-backdrop" />
        <Dialog.Content className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[95vw] max-w-md glass-card p-6 shadow-2xl">
          {result ? (
            <div className="space-y-4">
              <Dialog.Title className="text-lg font-bold">Салон создан!</Dialog.Title>
              <div className="glass-card-sm p-3">
                <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>API Key (сохраните!)</div>
                <code className="font-mono text-sm break-all" style={{ color: "var(--accent)" }}>{result.api_key}</code>
              </div>
              <button onClick={onCreated} className="w-full rounded-xl py-3 font-medium text-sm" style={{ background: "var(--accent)", color: "#06080f" }}>
                Готово
              </button>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-3">
              <Dialog.Title className="text-lg font-bold">Новый салон</Dialog.Title>
              <input
                value={name}
                onChange={(e) => { setName(e.target.value); if (!slug) setSlug(e.target.value.toLowerCase().replace(/\s+/g, "-")); }}
                placeholder="Название салона"
                className="w-full glass-input px-4 py-2.5 text-sm"
              />
              <input
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="Slug (URL-friendly)"
                className="w-full glass-input px-4 py-2.5 text-sm font-mono"
              />
              <input
                value={contactEmail}
                onChange={(e) => setContactEmail(e.target.value)}
                placeholder="Контактный email"
                type="email"
                className="w-full glass-input px-4 py-2.5 text-sm"
              />
              <div className="flex gap-3">
                <select
                  value={plan}
                  onChange={(e) => setPlan(e.target.value)}
                  className="flex-1 glass-input px-4 py-2.5 text-sm"
                >
                  <option value="free">Free</option>
                  <option value="pro">Pro</option>
                  <option value="enterprise">Enterprise</option>
                </select>
                <input
                  type="number"
                  value={maxCams}
                  onChange={(e) => setMaxCams(parseInt(e.target.value))}
                  placeholder="Max cameras"
                  className="w-24 glass-input px-4 py-2.5 text-sm"
                />
              </div>
              {error && (
                <div className="flex items-center gap-2 text-xs" style={{ color: "var(--red)" }}>
                  <AlertTriangle size={12} />
                  {error}
                </div>
              )}
              <div className="flex gap-2 pt-2">
                <Dialog.Close asChild>
                  <button type="button" className="flex-1 rounded-xl py-2.5 text-sm glass-card-sm transition-colors" style={{ color: "var(--text-muted)" }}>
                    Отмена
                  </button>
                </Dialog.Close>
                <button
                  type="submit"
                  disabled={loading || !name}
                  className="flex-1 rounded-xl py-2.5 font-medium text-sm disabled:opacity-50 transition-all"
                  style={{ background: "var(--accent)", color: "#06080f" }}
                >
                  {loading ? "Создание…" : "Создать"}
                </button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function AddUserForm({
  tenantId,
  onClose,
  onCreated,
}: {
  tenantId: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("admin");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handle = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await adminApi.createUser(tenantId, { email, password, name, role });
      onCreated();
    } catch {
      setError("Ошибка создания пользователя");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handle} className="space-y-2 glass-card-sm p-3 mt-2">
      <div className="text-xs font-medium">Новый пользователь</div>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email" type="email" className="w-full glass-input px-3 py-2 text-sm" />
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя" className="w-full glass-input px-3 py-2 text-sm" />
      <input value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Пароль" type="password" className="w-full glass-input px-3 py-2 text-sm" />
      <select value={role} onChange={(e) => setRole(e.target.value)} className="w-full glass-input px-3 py-2 text-sm">
        <option value="admin">Admin</option>
        <option value="viewer">Viewer</option>
      </select>
      {error && (
        <div className="flex items-center gap-1 text-[11px]" style={{ color: "var(--red)" }}>
          <AlertTriangle size={10} />
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <button type="button" onClick={onClose} className="flex-1 rounded-xl py-1.5 text-xs glass-card-sm" style={{ color: "var(--text-muted)" }}>
          Отмена
        </button>
        <button type="submit" disabled={loading || !email || !password} className="flex-1 rounded-xl py-1.5 text-xs font-medium disabled:opacity-50" style={{ background: "var(--accent)", color: "#06080f" }}>
          Создать
        </button>
      </div>
    </form>
  );
}

function SetupGuide() {
  const [open, setOpen] = useState(false);

  return (
    <div className="glass-card p-4 space-y-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="text-sm font-medium">Настройка платформы</span>
        <ChevronDown
          size={16}
          style={{ color: "var(--text-muted)", transform: open ? "rotate(180deg)" : "none", transition: "transform 0.2s" }}
        />
      </button>

      {open && (
        <div className="text-[11px] leading-relaxed space-y-4 pt-2" style={{ color: "var(--text-dim)" }}>
          {/* AI Keys */}
          <div className="space-y-2">
            <p className="font-medium text-xs" style={{ color: "var(--accent)" }}>1. AI ключи (LLM)</p>
            <p>Для работы ИИ-нарративов и чат-ассистента нужен API ключ Anthropic или OpenAI.</p>
            <div className="glass-card-sm p-2.5 space-y-1.5">
              <p className="font-medium" style={{ color: "var(--text)" }}>Anthropic (рекомендуется):</p>
              <ol className="list-decimal list-inside space-y-0.5">
                <li>Зайдите на <span style={{ color: "var(--accent)" }}>console.anthropic.com</span></li>
                <li>Зарегистрируйтесь / войдите</li>
                <li>Перейдите в Settings → API Keys → Create Key</li>
                <li>Скопируйте ключ <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>sk-ant-...</code></li>
                <li>Вставьте в <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>ANTHROPIC_API_KEY</code> в .env</li>
              </ol>
            </div>
            <div className="glass-card-sm p-2.5 space-y-1.5">
              <p className="font-medium" style={{ color: "var(--text)" }}>OpenAI (альтернатива):</p>
              <ol className="list-decimal list-inside space-y-0.5">
                <li>Зайдите на <span style={{ color: "var(--accent)" }}>platform.openai.com</span></li>
                <li>API Keys → Create new secret key</li>
                <li>Вставьте в <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>OPENAI_API_KEY</code> и <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>LLM_PROVIDER=openai</code></li>
              </ol>
            </div>
          </div>

          {/* Telegram */}
          <div className="space-y-2">
            <p className="font-medium text-xs" style={{ color: "var(--accent)" }}>2. Telegram бот</p>
            <div className="glass-card-sm p-2.5 space-y-1.5">
              <ol className="list-decimal list-inside space-y-0.5">
                <li>Откройте <span style={{ color: "var(--accent)" }}>@BotFather</span> в Telegram</li>
                <li>Отправьте <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>/newbot</code></li>
                <li>Придумайте имя и username</li>
                <li>Скопируйте токен в <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>TELEGRAM_BOT_TOKEN</code> в .env</li>
                <li>Перезапустите сервер</li>
                <li>В карточке салона → Telegram → отправьте <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>/start api_key</code> боту</li>
              </ol>
            </div>
          </div>

          {/* Hik-Connect Cloud */}
          <div className="space-y-2">
            <p className="font-medium text-xs" style={{ color: "var(--accent)" }}>3. Hik-Connect (камеры через облако)</p>
            <div className="glass-card-sm p-2.5 space-y-1.5">
              <p>Используйте тот же логин и пароль, что в приложении <b>Hik-Connect</b> на телефоне.</p>
              <p>Камеры подключаются через интернет — не нужен проброс портов.</p>
              <div className="font-mono text-[10px] px-2 py-1.5 rounded-lg mt-1" style={{ background: "var(--surface-2)", color: "var(--accent)" }}>
                HIKCONNECT_EMAIL=your@email.com<br/>
                HIKCONNECT_PASSWORD=your_password<br/>
                HIKCONNECT_REGION=ru
              </div>
              <p className="pt-1">Или войдите прямо здесь:</p>
            </div>
            <HikConnectSetup />
          </div>

          {/* RTSP (альтернатива) */}
          <div className="space-y-2">
            <p className="font-medium text-xs" style={{ color: "var(--accent)" }}>4. Камеры по RTSP (альтернатива)</p>
            <div className="glass-card-sm p-2.5 space-y-1.5">
              <p>Если камеры в одной сети с сервером — можно подключить напрямую по RTSP без облака.</p>
              <p>Камеры → Добавить → RTSP → ввести IP/логин/пароль.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function HikConnectSetup() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [region, setRegion] = useState("ru");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ connected: boolean; cameras_found: number } | null>(null);
  const [error, setError] = useState("");

  const handleConnect = async () => {
    if (!email || !password) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await hikconnectApi.connect(email, password, region);
      setResult({ connected: data.connected, cameras_found: data.cameras_found });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка подключения");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="glass-card-sm p-2.5 space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email / телефон"
          className="glass-input px-2 py-1.5 text-[11px]"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Пароль"
          type="password"
          className="glass-input px-2 py-1.5 text-[11px]"
        />
      </div>
      <div className="flex gap-2">
        <select
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          className="glass-input px-2 py-1.5 text-[11px] flex-1"
          style={{ color: "var(--text)", background: "var(--surface-2)" }}
        >
          <option value="eu">Европа (EU)</option>
          <option value="ru">Россия (RU)</option>
          <option value="us">США (US)</option>
          <option value="cn">Китай (CN)</option>
          <option value="sg">Сингапур (SG)</option>
        </select>
        <button
          onClick={handleConnect}
          disabled={loading || !email || !password}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-medium disabled:opacity-40"
          style={{ background: "var(--accent)", color: "#06080f" }}
        >
          {loading ? "..." : <><Cloud size={12} /> Войти</>}
        </button>
      </div>
      {result && (
        <div className="text-[11px] flex items-center gap-1.5" style={{ color: "var(--green)" }}>
          <span className="w-2 h-2 rounded-full" style={{ background: "var(--green)" }} />
          Подключено! Найдено камер: {result.cameras_found}
        </div>
      )}
      {error && (
        <div className="text-[11px]" style={{ color: "var(--red)" }}>{error}</div>
      )}
    </div>
  );
}

function TelegramSetup({ tenantApiKey }: { tenantApiKey: string }) {
  const [copied, setCopied] = useState(false);

  const copyCmd = () => {
    navigator.clipboard.writeText(`/start ${tenantApiKey}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="glass-card-sm p-3 space-y-3">
      <div className="flex items-center gap-2">
        <Send size={14} style={{ color: "var(--accent)" }} />
        <span className="text-xs font-medium" style={{ color: "var(--text)" }}>
          Telegram уведомления
        </span>
      </div>

      <div className="text-[11px] leading-relaxed space-y-2" style={{ color: "var(--text-dim)" }}>
        <p className="font-medium" style={{ color: "var(--text)" }}>Как создать бота (один раз):</p>
        <ol className="space-y-1.5 list-decimal list-inside">
          <li>Откройте Telegram, найдите <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)", color: "var(--accent)" }}>@BotFather</code></li>
          <li>Отправьте <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>/newbot</code></li>
          <li>Введите имя: <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>Sentinel Alert</code></li>
          <li>Введите username: <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>MyCompanyAlertBot</code> (уникальный)</li>
          <li>Скопируйте токен вида <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>123456:ABC-DEF...</code></li>
          <li>Вставьте токен в <code className="font-mono px-1 py-px rounded" style={{ background: "var(--surface-2)" }}>TELEGRAM_BOT_TOKEN</code> в настройках сервера (.env)</li>
          <li>Перезапустите backend</li>
        </ol>

        <p className="font-medium pt-1" style={{ color: "var(--text)" }}>Подключить салон к боту:</p>
        <p>
          Без API-ключа бот ничего не покажет (только приветствие).
          Откройте бота и отправьте команду — появятся кнопки: статус, алерты, история, сводка:
        </p>
      </div>

      <div
        className="font-mono text-xs px-3 py-2 rounded-xl select-all cursor-pointer flex items-center justify-between"
        style={{ background: "var(--surface-2)", color: "var(--accent)" }}
        onClick={copyCmd}
        title="Нажмите чтобы скопировать"
      >
        <span>/start {tenantApiKey}</span>
        <span className="text-[10px]" style={{ color: "var(--text-dim)" }}>
          {copied ? "Скопировано!" : "Копировать"}
        </span>
      </div>

      <p className="text-[10px]" style={{ color: "var(--text-dim)", opacity: 0.7 }}>
        После этого бот будет отправлять алерты (отсутствие персонала, подозрительная активность и т.д.) в ваш Telegram.
      </p>
    </div>
  );
}
