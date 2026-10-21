const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
const AUTH_BASE = process.env.NEXT_PUBLIC_API_URL?.replace("/api/v1", "") ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY ?? "";

// ── Auth headers ────────────────────────────────────────────────────────────

function authHeaders(): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const token = typeof window !== "undefined"
    ? localStorage.getItem("sentinel_token") ?? API_KEY
    : API_KEY;
  if (token) {
    h["Authorization"] = `Bearer ${token}`;
  }
  return h;
}

async function req<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(),
    ...opts,
  });
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("sentinel:auth-required"));
    }
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

// ── User info ───────────────────────────────────────────────────────────────

export interface UserInfo {
  id: string;
  email: string;
  name: string;
  role: string;
  tenant_id: string;
  tenant_name: string;
}

function getUserInfo(): UserInfo | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("sentinel_user");
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

// ── Auth API ────────────────────────────────────────────────────────────────

export const authApi = {
  loginWithEmail: async (email: string, password: string): Promise<UserInfo> => {
    const res = await fetch(`${AUTH_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) throw new Error("Неверный email или пароль");
    const data = await res.json() as { access_token: string; user: UserInfo };
    if (typeof window !== "undefined") {
      localStorage.setItem("sentinel_token", data.access_token);
      localStorage.setItem("sentinel_user", JSON.stringify(data.user));
    }
    return data.user;
  },

  loginWithApiKey: async (apiKey: string): Promise<UserInfo> => {
    const res = await fetch(`${AUTH_BASE}/auth/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    });
    if (!res.ok) throw new Error("Неверный ключ");
    const data = await res.json() as { access_token: string; user: UserInfo };
    if (typeof window !== "undefined") {
      localStorage.setItem("sentinel_token", data.access_token);
      localStorage.setItem("sentinel_user", JSON.stringify(data.user));
    }
    return data.user;
  },

  logout: () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("sentinel_token");
      localStorage.removeItem("sentinel_user");
    }
  },

  isAuthenticated: (): boolean => {
    if (typeof window === "undefined") return false;
    return !!(localStorage.getItem("sentinel_token") || API_KEY);
  },

  getUser: getUserInfo,

  isSuperadmin: (): boolean => getUserInfo()?.role === "superadmin",
};

// ── Admin API ───────────────────────────────────────────────────────────────

export interface TenantSummary {
  id: string;
  name: string;
  slug: string;
  plan: string;
  max_cameras: number;
  is_active: boolean;
  created_at: string;
  users_count: number;
  agents_count: number;
  visits_today: number;
}

export interface TenantDetail extends TenantSummary {
  api_key: string;
  contact_email?: string;
  contact_phone?: string;
  address?: string;
  users: { id: string; email: string; name: string; role: string; is_active: boolean }[];
  agents: { id: string; agent_name: string; hostname: string; status: string; cameras_count: number; last_heartbeat?: string }[];
}

export interface GlobalStats {
  total_tenants: number;
  active_tenants: number;
  total_users: number;
  total_agents: number;
  agents_online: number;
  total_visits_today: number;
  total_alerts_today: number;
}

async function adminReq<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${AUTH_BASE}${path}`, {
    headers: authHeaders(),
    ...opts,
  });
  if (res.status === 401 || res.status === 403) {
    throw new Error("Access denied");
  }
  if (!res.ok) throw new Error(`Admin API error ${res.status}`);
  return res.json() as Promise<T>;
}

export const adminApi = {
  stats: () => adminReq<GlobalStats>("/admin/stats"),
  listTenants: () => adminReq<TenantSummary[]>("/admin/tenants"),
  getTenant: (id: string) => adminReq<TenantDetail>(`/admin/tenants/${id}`),
  createTenant: (data: { name: string; slug: string; plan?: string; max_cameras?: number; contact_email?: string }) =>
    adminReq<{ id: string; name: string; slug: string; api_key: string }>("/admin/tenants", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateTenant: (id: string, data: Record<string, unknown>) =>
    adminReq<{ updated: string }>(`/admin/tenants/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  regenerateKey: (id: string) =>
    adminReq<{ api_key: string }>(`/admin/tenants/${id}/regenerate-key`, { method: "POST" }),
  createUser: (tenantId: string, data: { email: string; password: string; name?: string; role?: string }) =>
    adminReq<{ id: string; email: string; name: string; role: string }>(`/admin/tenants/${tenantId}/users`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteTenant: (id: string) =>
    adminReq<{ deleted: string }>(`/admin/tenants/${id}`, { method: "DELETE" }),
  deleteUser: (tenantId: string, userId: string) =>
    adminReq<{ deleted: string }>(`/admin/tenants/${tenantId}/users/${userId}`, { method: "DELETE" }),
};

// ── Cameras ─────────────────────────────────────────────────────────────────

export interface TestConnectionResult {
  ok: boolean;
  width?: number;
  height?: number;
  fps?: number;
  error?: string;
}

export const camerasApi = {
  list: () => req<Camera[]>("/cameras/"),
  add: (body: AddCameraBody) =>
    req<Camera>("/cameras/", { method: "POST", body: JSON.stringify(body) }),
  remove: (id: string) => req<void>(`/cameras/${id}`, { method: "DELETE" }),
  heatmap: (id: string) => req<HeatmapData>(`/cameras/${id}/heatmap`),
  testConnection: (url: string) =>
    req<TestConnectionResult>("/cameras/test", { method: "POST", body: JSON.stringify({ url }) }),
};

// ── Hik-Connect ─────────────────────────────────────────────────────────────

export interface HikDevice {
  serial: string;
  name: string;
  type: string;
  version: string;
}

export interface HikCamera {
  device_serial: string;
  camera_id: string;
  name: string;
  channel_no: number;
  status: "online" | "offline";
}

export interface HikConnectResponse {
  connected: boolean;
  devices_found: number;
  cameras_found: number;
  devices: HikDevice[];
  cameras: HikCamera[];
}

export const hikconnectApi = {
  connect: (email: string, password: string, region: string = "ru") =>
    req<HikConnectResponse>("/hikconnect/connect", {
      method: "POST",
      body: JSON.stringify({ email, password, region }),
    }),
  listCameras: () =>
    req<{ cameras: HikCamera[] }>("/hikconnect/cameras"),
  importCamera: (body: { device_serial: string; channel_no?: number; name?: string; location_id?: string; quality?: number }) =>
    req<Camera>("/hikconnect/import", { method: "POST", body: JSON.stringify(body) }),
  refreshStream: (cameraId: string) =>
    req<{ refreshed: string; url: string }>(`/hikconnect/refresh/${cameraId}`, { method: "POST" }),
};

// ── Persons ─────────────────────────────────────────────────────────────────

export const personsApi = {
  list: (category?: string) =>
    req<Person[]>(`/persons/${category ? `?category=${category}` : ""}`.replace("/?", "?")),
  get: (id: string) => req<Person>(`/persons/${id}`),
  enroll: async (form: FormData) => {
    const h: Record<string, string> = {};
    const token = typeof window !== "undefined"
      ? localStorage.getItem("sentinel_token") ?? API_KEY
      : API_KEY;
    if (token) h["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${BASE}/persons/enroll`, {
      method: "POST",
      body: form,
      headers: h,
    });
    if (!res.ok) throw new Error(`Enroll failed: ${res.status}`);
    return res.json() as Promise<{ person_id: string; name: string; category: string }>;
  },
};

// ── Zones ───────────────────────────────────────────────────────

export interface Zone {
  id: string;
  camera_id: string;
  tenant_id: string;
  name: string;
  zone_type: string;
  polygon: number[][];
  is_active: boolean;
  staff_required: boolean;
  max_absence_seconds: number;
  max_wait_seconds: number;
  created_at: string;
  updated_at: string;
}

export interface ZoneCreateBody {
  name: string;
  zone_type: string;
  polygon: number[][];
  staff_required?: boolean;
  max_absence_seconds?: number;
  max_wait_seconds?: number;
}

export const zonesApi = {
  list: () => req<Zone[]>("/zones"),
  listForCamera: (cameraId: string) => req<Zone[]>(`/zones/camera/${cameraId}`),
  create: (cameraId: string, body: ZoneCreateBody) =>
    req<Zone>(`/zones/camera/${cameraId}`, { method: "POST", body: JSON.stringify(body) }),
  update: (zoneId: string, body: Partial<ZoneCreateBody> & { is_active?: boolean }) =>
    req<Zone>(`/zones/${zoneId}`, { method: "PUT", body: JSON.stringify(body) }),
  delete: (zoneId: string) =>
    req<{ deleted: string }>(`/zones/${zoneId}`, { method: "DELETE" }),
  redbookPresets: () =>
    req<{ name: string; description: string; presets: Array<Record<string, unknown>> }>("/zones/presets/redbook"),
  applyRedbookPresets: (cameraId: string, body?: { frame_width?: number; frame_height?: number; replace_existing?: boolean }) =>
    req<{ camera_id: string; applied: number; zones: Array<Record<string, unknown>>; note: string }>(
      `/zones/camera/${cameraId}/presets/redbook`,
      { method: "POST", body: JSON.stringify(body ?? {}) },
    ),
};

// ── Telegram ────────────────────────────────────────────────────

export const tenantApi = {
  setTelegramChat: (tenantId: string, chatId: string) =>
    adminReq<{ updated: string }>("/admin/telegram", {
      method: "PUT",
      body: JSON.stringify({ tenant_id: tenantId, telegram_chat_id: chatId }),
    }),
};

// ── Analytics ───────────────────────────────────────────────────────────────

export interface RedBookRemarksResponse {
  total: number;
  critical: number;
  score: number;
  standard: string;
  remarks: Alert[];
  note: string;
}

export const analyticsApi = {
  visits: (start: string, end: string, category = "all") =>
    req<Visit[]>(`/analytics/visits?start=${start}&end=${end}&category=${category}`),
  alerts: (start: string, severity = "all") =>
    req<Alert[]>(`/analytics/alerts?start=${start}&severity=${severity}`),
  occupancy: (date: string) =>
    req<OccupancyPoint[]>(`/analytics/occupancy?date=${date}`),
  summaries: (location?: string, limit = 20) =>
    req<NarrativeSummary[]>(`/analytics/summaries?${location ? `location_id=${location}&` : ""}limit=${limit}`),
  redbookRemarks: (start: string) =>
    req<RedBookRemarksResponse>(`/analytics/redbook/remarks?start=${encodeURIComponent(start)}`),
};

// ── Chat ────────────────────────────────────────────────────────────────────

export const chatApi = {
  ask: (question: string, history: ChatMessage[]) =>
    req<{ answer: string }>("/chat/", {
      method: "POST",
      body: JSON.stringify({ question, history }),
    }),
};

// ── Types ───────────────────────────────────────────────────────────────────

export interface Camera {
  id: string;
  name: string;
  url: string;
  location_id: string;
  enabled: boolean;
  running: boolean;
}

export interface AddCameraBody {
  id: string;
  url: string;
  name?: string;
  location_id?: string;
  fps_inference?: number;
}

export interface Person {
  id: string;
  name: string;
  category: string;
  visit_count: number;
  phone?: string;
  email?: string;
  notes?: string;
}

export interface Visit {
  visit_id: number;
  person: { id: string; name: string; category: string; visit_count: number };
  entered_at: string;
  dwell_seconds?: number;
  location_id: string;
}

export interface Alert {
  id: number;
  type: string;
  severity: string;
  description: string;
  camera_id: string;
  acknowledged: boolean;
  created_at: string;
}

export interface OccupancyPoint {
  hour: string;
  visits: number;
}

export interface NarrativeSummary {
  id: number;
  narrative: string;
  occupancy: number;
  mood: string;
  created_at: string;
}

export interface HeatmapData {
  camera_id: string;
  width: number;
  height: number;
  data: number[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}
