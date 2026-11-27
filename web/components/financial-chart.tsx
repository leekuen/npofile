"use client";

import { useState } from "react";

import { formatMoney } from "@/lib/format";

/** 近 5 年財務趨勢折線圖（LK-17）：總收入、總支出、年底淨資產，一條 y 軸（都是元）。
 *  顏色經 dataviz validate_palette 檢查過（色盲可分）；每條線尾端直接標名稱，圖上方也有圖例，不只靠顏色。 */

export type ChartRow = { year: number; revenue: number | null; expenses: number | null; netAssets: number | null };

const SERIES = [
  { key: "revenue", label: "總收入", color: "#4150b6", dash: undefined },
  { key: "expenses", label: "總支出", color: "#c2610f", dash: "6 4" },
  { key: "netAssets", label: "年底淨資產", color: "#0f8a6c", dash: "2 4" },
] as const;
type SeriesKey = (typeof SERIES)[number]["key"];

const W = 640;
const H = 260;
const PAD = { top: 16, right: 96, bottom: 32, left: 64 };
const SURFACE = "#ffffff";

/** 軸與尾端標籤用的短寫法：1.2 億、3,400 萬 */
export function formatCompact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(abs >= 1e9 ? 0 : 1)} 億`;
  if (abs >= 1e4) return `${Math.round(v / 1e4).toLocaleString("zh-TW")} 萬`;
  return v.toLocaleString("zh-TW");
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}

export function FinancialChart({ rows }: { rows: ChartRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const data = [...rows].sort((a, b) => a.year - b.year);
  const values = data.flatMap((r) => SERIES.map((s) => r[s.key])).filter((v): v is number => v !== null);
  const minV = Math.min(0, ...values);
  const maxV = niceMax(Math.max(...values, 0));
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (data.length === 1 ? plotW / 2 : (i * plotW) / (data.length - 1));
  const y = (v: number) => PAD.top + plotH - ((v - minV) / (maxV - minV)) * plotH;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((t) => minV + t * (maxV - minV));

  // 尾端標籤：兩條線尾端太近（< 14px）時只留圖例與滑鼠提示，不硬擠
  const ends = SERIES.map((s) => {
    for (let i = data.length - 1; i >= 0; i--) {
      const v = data[i][s.key];
      if (v !== null) return { key: s.key, i, v, py: y(v) };
    }
    return null;
  });
  const showEnd = (k: SeriesKey) => {
    const me = ends.find((e) => e?.key === k);
    if (!me) return false;
    return ends.every((o) => !o || o.key === k || Math.abs(o.py - me.py) >= 14 || SERIES.findIndex((s) => s.key === o.key) > SERIES.findIndex((s) => s.key === k));
  };

  const hovered = hover === null ? null : data[hover];

  return (
    <figure className="relative">
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-700" aria-hidden>
        {SERIES.map((s) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <svg width="20" height="8" aria-hidden>
              <line x1="0" y1="4" x2="20" y2="4" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} />
            </svg>
            {s.label}
          </li>
        ))}
      </ul>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-auto w-full"
        role="img"
        aria-label={`近 ${data.length} 年總收入、總支出、年底淨資產折線圖，數字見下方表格`}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="#e1e4f0" strokeWidth="1" />
            <text x={PAD.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle" className="fill-ink-500 text-[11px] tabular-nums">
              {formatCompact(t)}
            </text>
          </g>
        ))}
        {data.map((r, i) => (
          <text key={r.year} x={x(i)} y={H - 10} textAnchor="middle" className="fill-ink-600 text-[11px] tabular-nums">
            {r.year} 年
          </text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} stroke="#9ca2bf" strokeWidth="1" />}
        {SERIES.map((s) => {
          // 某一年沒有數字就斷線，不拿前後年硬連
          const segments: string[] = [];
          let cur: string[] = [];
          data.forEach((r, i) => {
            const v = r[s.key];
            if (v === null) {
              if (cur.length) segments.push(cur.join(" "));
              cur = [];
            } else cur.push(`${cur.length ? "L" : "M"}${x(i)},${y(v)}`);
          });
          if (cur.length) segments.push(cur.join(" "));
          const end = ends.find((e) => e?.key === s.key);
          return (
            <g key={s.key}>
              {segments.map((d) => (
                <path key={d} d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash} />
              ))}
              {data.map((r, i) =>
                r[s.key] === null ? null : (
                  <circle key={r.year} cx={x(i)} cy={y(r[s.key] as number)} r={hover === i ? 5 : 4} fill={s.color} stroke={SURFACE} strokeWidth="2" />
                ),
              )}
              {end && showEnd(s.key) && (
                <text x={x(end.i) + 10} y={end.py} dominantBaseline="middle" className="fill-ink-800 text-[12px]">
                  {s.label}
                </text>
              )}
            </g>
          );
        })}
        {/* 滑鼠提示的感應區：一年一欄，比點大很多 */}
        {data.map((r, i) => {
          const half = data.length === 1 ? plotW / 2 : plotW / (data.length - 1) / 2;
          return (
            <rect
              key={r.year}
              x={x(i) - half}
              y={PAD.top}
              width={half * 2}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onTouchStart={() => setHover(i)}
            />
          );
        })}
      </svg>
      {hovered && hover !== null && (
        <div
          className="pointer-events-none absolute top-8 z-10 w-44 rounded-lg border border-ink-200 bg-white p-2.5 text-xs shadow-md"
          style={{
            left: `${(x(hover) / W) * 100}%`,
            transform: x(hover) > W / 2 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
          }}
          role="status"
        >
          <p className="mb-1 font-semibold text-ink-900">民國 {hovered.year} 年</p>
          <dl className="space-y-0.5">
            {SERIES.map((s) => (
              <div key={s.key} className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1 text-ink-600">
                  <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden />
                  {s.label}
                </dt>
                <dd className="font-num tabular-nums text-ink-900">{formatMoney(hovered[s.key])}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </figure>
  );
}
