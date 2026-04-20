"use client";

import { useEffect, useRef, useState } from "react";
import { useSentinelStore } from "@/lib/store";

export function HeatmapView() {
  const cameras = useSentinelStore((s) => s.cameras);
  const heatmaps = useSentinelStore((s) => s.heatmaps);
  const [selected, setSelected] = useState<string>("");

  useEffect(() => {
    if (cameras.length > 0 && !selected) setSelected(cameras[0].id);
  }, [cameras, selected]);

  const heatmap = heatmaps[selected];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="text-xs font-mono uppercase tracking-widest" style={{ color: "var(--text-dim)" }}>
          Тепловая карта активности
        </span>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="ml-auto text-xs px-3 py-1.5 rounded-lg outline-none"
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            color: "var(--text)",
          }}
        >
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name || c.id}
            </option>
          ))}
        </select>
      </div>

      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
      >
        {heatmap ? (
          <HeatmapCanvas data={heatmap.data} width={heatmap.width} height={heatmap.height} />
        ) : (
          <div
            className="flex items-center justify-center h-64 text-sm"
            style={{ color: "var(--text-dim)" }}
          >
            {cameras.length === 0
              ? "Нет подключённых камер"
              : "Ожидание данных тепловой карты..."}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 text-xs" style={{ color: "var(--text-dim)" }}>
        <span>Активность:</span>
        <div
          className="flex-1 h-3 rounded"
          style={{
            background:
              "linear-gradient(90deg, rgba(0,229,255,0.1), rgba(0,229,255,0.5), rgba(124,58,237,0.7), rgba(255,59,92,1))",
          }}
        />
        <span>Высокая</span>
      </div>
    </div>
  );
}

function HeatmapCanvas({
  data,
  width,
  height,
}: {
  data: number[];
  width: number;
  height: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const cellW = canvas.width / width;
    const cellH = canvas.height / height;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const val = data[y * width + x] / 255;
        if (val < 0.01) continue;
        ctx.fillStyle = valToColor(val);
        ctx.fillRect(x * cellW, y * cellH, cellW, cellH);
      }
    }
  }, [data, width, height]);

  return (
    <canvas
      ref={canvasRef}
      width={1280}
      height={720}
      className="w-full h-auto"
      style={{ display: "block", imageRendering: "pixelated" }}
    />
  );
}

function valToColor(v: number): string {
  if (v < 0.33) {
    const t = v / 0.33;
    return `rgba(0,229,255,${0.1 + t * 0.4})`;
  } else if (v < 0.66) {
    const t = (v - 0.33) / 0.33;
    return `rgba(${Math.round(t * 124)},${Math.round(58 + t * 58)},237,${0.5 + t * 0.2})`;
  } else {
    const t = (v - 0.66) / 0.34;
    return `rgba(255,${Math.round(59 - t * 59)},${Math.round(92 - t * 92)},${0.7 + t * 0.3})`;
  }
}
