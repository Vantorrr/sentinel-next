/**
 * WebSocket client — connects to the Sentinel backend event stream.
 * Auto-reconnects on disconnect with exponential backoff.
 */
import { camerasApi } from "./api";
import { SentinelEvent, useSentinelStore } from "./store";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/events";

let ws: WebSocket | null = null;
let reconnectDelay = 1000;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function getWsUrl(): string {
  const token = typeof window !== "undefined"
    ? localStorage.getItem("sentinel_token") ?? process.env.NEXT_PUBLIC_API_KEY ?? ""
    : "";
  if (token) {
    const sep = WS_URL.includes("?") ? "&" : "?";
    return `${WS_URL}${sep}token=${encodeURIComponent(token)}`;
  }
  return WS_URL;
}

export function connectEventStream() {
  if (typeof window === "undefined") return;
  if (ws && ws.readyState <= WebSocket.OPEN) return;

  const store = useSentinelStore.getState();
  ws = new WebSocket(getWsUrl());

  ws.onopen = () => {
    console.info("[Sentinel WS] connected");
    store.setWsConnected(true);
    reconnectDelay = 1000;
    camerasApi
      .list()
      .then((list) => useSentinelStore.getState().setCameras(list))
      .catch(() => undefined);
  };

  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data as string);
      if (data.type === "ping") return;

      const event = data as SentinelEvent;
      store.addEvent(event);

      // Side effects based on event type
      switch (event.type) {
        case "person.detected":
          store.addTrack(event.camera_id, event.track_id ?? "");
          break;

        case "person.lost":
          store.removeTrack(event.camera_id, event.track_id ?? "");
          break;

        case "occupancy.update":
          store.setOccupancy(event.payload.count as number);
          break;

        case "llm.summary":
          store.addSummary({
            narrative: event.payload.narrative as string,
            occupancy: event.payload.occupancy as number,
            mood: event.payload.mood as string,
            alerts: (event.payload.alerts as string[]) ?? [],
            insights: (event.payload.insights as string[]) ?? [],
            location_id: event.location_id,
            timestamp_ms: event.timestamp_ms,
          });
          break;

        case "fraud.alert":
        case "zone.violation":
        case "staff.absent":
        case "client.unattended":
          store.incrementAlerts();
          break;

        case "heatmap.update":
          store.setHeatmap({
            camera_id: event.camera_id,
            width: event.payload.width as number,
            height: event.payload.height as number,
            data: event.payload.data as number[],
          });
          break;
      }
    } catch (err) {
      console.error("[Sentinel WS] parse error", err);
    }
  };

  ws.onerror = () => {
    // Soft log — Event objects tripped Next.js dev overlay when console.error'd
    console.warn("[Sentinel WS] connection error (will reconnect)");
  };

  ws.onclose = () => {
    store.setWsConnected(false);
    console.warn(`[Sentinel WS] disconnected — reconnect in ${reconnectDelay}ms`);
    reconnectTimer = setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, 30000);
      connectEventStream();
    }, reconnectDelay);
  };
}

export function disconnectEventStream() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  ws?.close();
  ws = null;
}

export function sendWsFilter(locationIds: string[], eventTypes: string[]) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ location_ids: locationIds, event_types: eventTypes }));
  }
}
