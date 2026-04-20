/**
 * Demo mode — generates synthetic SentinelEvents locally so the
 * dashboard looks alive without a real backend or camera.
 *
 * Activated when the WebSocket fails to connect after 3 seconds,
 * OR when ?demo=1 is in the URL.
 */

import { useSentinelStore, type EventType, type SentinelEvent } from "./store";

const NAMES = ["Андрей", "Маша", "Иван", "VIP Клиент", "Новый гость", "Сотрудник Алина"];
const CATEGORIES = ["staff", "regular", "new", "vip", "new", "staff"];
const CAMERAS = ["cam-вход", "cam-зал", "cam-касса"];

let demoInterval: ReturnType<typeof setInterval> | null = null;
let eventCounter = 0;

function makeEvent(
  type: EventType,
  cameraIdx: number,
  personIdx: number,
  extra: Record<string, unknown> = {}
): SentinelEvent {
  eventCounter++;
  return {
    id: `demo-${eventCounter}`,
    type,
    camera_id: CAMERAS[cameraIdx % CAMERAS.length],
    location_id: "demo",
    track_id: `track-${eventCounter}`,
    person_id: `person-${personIdx}`,
    confidence: 0.82 + Math.random() * 0.15,
    payload: {
      name: NAMES[personIdx % NAMES.length],
      category: CATEGORIES[personIdx % CATEGORIES.length],
      ...extra,
    },
    timestamp_ms: Date.now(),
  };
}

export function startDemoMode() {
  if (demoInterval) return;
  const store = useSentinelStore.getState();
  store.setWsConnected(true);

  let tick = 0;

  // Seed some initial cameras
  store.setCameras([
    { id: "cam-вход", name: "Вход", url: "demo", location_id: "demo", enabled: true, running: true },
    { id: "cam-зал", name: "Зал", url: "demo", location_id: "demo", enabled: true, running: true },
    { id: "cam-касса", name: "Касса", url: "demo", location_id: "demo", enabled: true, running: true },
  ]);

  // Initial heatmap
  store.setHeatmap({
    camera_id: "cam-зал",
    width: 64,
    height: 36,
    data: Array.from({ length: 64 * 36 }, () => Math.floor(Math.random() * 120)),
  });

  // Immediate summary
  store.addSummary({
    narrative: "Система запущена в демо-режиме. Зал пустой, персонал на месте. Подозрительных нет.",
    occupancy: 0,
    mood: "нейтральное",
    alerts: [],
    insights: ["Демо-режим активен — добавьте реальную камеру для полной работы"],
    location_id: "demo",
    timestamp_ms: Date.now(),
  });

  demoInterval = setInterval(() => {
    tick++;
    const personIdx = Math.floor(Math.random() * NAMES.length);
    const camIdx = Math.floor(Math.random() * CAMERAS.length);

    if (tick % 3 === 0) {
      // Client enters
      const ev = makeEvent("client.entered", camIdx, personIdx);
      store.addEvent(ev);
      store.addTrack(ev.camera_id, ev.track_id!);

      setTimeout(() => {
        const idEv = makeEvent("face.identified", camIdx, personIdx);
        store.addEvent(idEv);
      }, 800);
    }

    if (tick % 5 === 0) {
      const cat = CATEGORIES[personIdx % CATEGORIES.length];
      if (cat === "vip") {
        store.addEvent(makeEvent("vip.detected", camIdx, personIdx));
        store.incrementAlerts(); // demo: VIP counts as noteworthy
      }
    }

    if (tick % 10 === 0) {
      // Person leaves
      const ev = makeEvent("person.lost", camIdx, personIdx, { dwell_seconds: 120 + Math.random() * 300 });
      store.addEvent(ev);
    }

    if (tick % 7 === 0) {
      // Occupancy update
      const occ = 2 + Math.floor(Math.random() * 8);
      store.setOccupancy(occ);
      store.addEvent(makeEvent("occupancy.update", camIdx, 0, { count: occ }));
    }

    if (tick % 20 === 0) {
      // LLM summary
      const summaries = [
        "Зашло 3 новых человека, Андрей на месте, работает. Касса в норме.",
        "Оживлённо: 6 человек в зале. VIP гость задержался — хороший знак.",
        "Маша сделала несколько продаж. Поток равномерный, тревог нет.",
        "Спокойный период. Персонал активен, новых клиентов пока нет.",
      ];
      const occ = 3 + Math.floor(Math.random() * 5);
      store.addSummary({
        narrative: summaries[tick % summaries.length],
        occupancy: occ,
        mood: Math.random() > 0.7 ? "позитивное" : "нейтральное",
        alerts: [],
        insights: tick % 40 === 0 ? ["Пик активности в 14:00–16:00"] : [],
        location_id: "demo",
        timestamp_ms: Date.now(),
      });
      store.setOccupancy(occ);
    }

    // Heatmap drift
    if (tick % 4 === 0) {
      store.setHeatmap({
        camera_id: CAMERAS[camIdx],
        width: 64,
        height: 36,
        data: Array.from({ length: 64 * 36 }, (_, i) => {
          const base = (i % 64 > 20 && i % 64 < 44) ? 100 : 20;
          return Math.min(255, Math.max(0, base + Math.floor(Math.random() * 40 - 20)));
        }),
      });
    }
  }, 2000); // new event every 2 seconds
}

export function stopDemoMode() {
  if (demoInterval) {
    clearInterval(demoInterval);
    demoInterval = null;
  }
}
