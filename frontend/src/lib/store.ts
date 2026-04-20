/**
 * Zustand global state — real-time surveillance data.
 */
import { create } from "zustand";

export type EventType =
  | "person.detected"
  | "person.lost"
  | "face.identified"
  | "face.unknown"
  | "client.entered"
  | "client.left"
  | "vip.detected"
  | "staff.detected"
  | "fraud.alert"
  | "zone.violation"
  | "zone.entered"
  | "zone.exited"
  | "staff.absent"
  | "client.unattended"
  | "heatmap.update"
  | "occupancy.update"
  | "llm.summary"
  | "camera.online"
  | "camera.offline"
  | "pipeline.error";

export interface SentinelEvent {
  id: string;
  type: EventType;
  camera_id: string;
  location_id: string;
  track_id?: string;
  person_id?: string;
  confidence: number;
  payload: Record<string, unknown>;
  timestamp_ms: number;
}

export interface Camera {
  id: string;
  name: string;
  url: string;
  location_id: string;
  enabled: boolean;
  running: boolean;
}

export interface NarrativeSummary {
  narrative: string;
  occupancy: number;
  mood: string;
  alerts: string[];
  insights: string[];
  location_id: string;
  timestamp_ms: number;
}

export interface OccupancyPoint {
  hour: string;
  count: number;
}

export interface HeatmapData {
  camera_id: string;
  width: number;
  height: number;
  data: number[];
}

interface SentinelStore {
  // Connection
  wsConnected: boolean;
  setWsConnected: (v: boolean) => void;

  // Events feed (rolling 200)
  events: SentinelEvent[];
  addEvent: (e: SentinelEvent) => void;
  clearEvents: () => void;

  // Cameras
  cameras: Camera[];
  setCameras: (c: Camera[]) => void;

  // Occupancy
  occupancyCurrent: number;
  setOccupancy: (n: number) => void;

  // Summaries
  latestSummary: NarrativeSummary | null;
  summaries: NarrativeSummary[];
  addSummary: (s: NarrativeSummary) => void;

  // Heatmaps
  heatmaps: Record<string, HeatmapData>;
  setHeatmap: (h: HeatmapData) => void;

  // Alerts (unread)
  unreadAlerts: number;
  incrementAlerts: () => void;
  clearAlerts: () => void;

  // Active tracks per camera
  activeTracks: Record<string, Set<string>>;
  addTrack: (cameraId: string, trackId: string) => void;
  removeTrack: (cameraId: string, trackId: string) => void;
}

export const useSentinelStore = create<SentinelStore>((set) => ({
  wsConnected: false,
  setWsConnected: (v) => set({ wsConnected: v }),

  events: [],
  addEvent: (e) =>
    set((s) => ({
      events: [e, ...s.events].slice(0, 100),
    })),
  clearEvents: () => set({ events: [] }),

  cameras: [],
  setCameras: (cameras) => set({ cameras }),

  occupancyCurrent: 0,
  setOccupancy: (n) => set({ occupancyCurrent: n }),

  latestSummary: null,
  summaries: [],
  addSummary: (s) =>
    set((state) => ({
      latestSummary: s,
      summaries: [s, ...state.summaries].slice(0, 50),
    })),

  heatmaps: {},
  setHeatmap: (h) =>
    set((s) => ({ heatmaps: { ...s.heatmaps, [h.camera_id]: h } })),

  unreadAlerts: 0,
  incrementAlerts: () => set((s) => ({ unreadAlerts: s.unreadAlerts + 1 })),
  clearAlerts: () => set({ unreadAlerts: 0 }),

  activeTracks: {},
  addTrack: (cameraId, trackId) =>
    set((s) => {
      const tracks = new Set(s.activeTracks[cameraId] || []);
      tracks.add(trackId);
      return { activeTracks: { ...s.activeTracks, [cameraId]: tracks } };
    }),
  removeTrack: (cameraId, trackId) =>
    set((s) => {
      const tracks = new Set(s.activeTracks[cameraId] || []);
      tracks.delete(trackId);
      return { activeTracks: { ...s.activeTracks, [cameraId]: tracks } };
    }),
}));
