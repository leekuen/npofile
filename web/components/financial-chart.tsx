"use client";

import { useEffect, useId, useRef, useState } from "react";

import { formatCompact, formatMoney } from "@/lib/format";

/** 近 5 年趨勢折線圖（LK-17 財務、LK-33 受捐款共用）：一條 y 軸（都是元），最多三條線。
 *  三個顏色依固定順序給，經 dataviz validate_palette 檢查過（色盲可分）；每條線另有不同虛線樣式、
 *  尾端直接標名稱、圖上方也有圖例，不只靠顏色。 */

const STYLES = [
  { color: "#4150b6", dash: undefined },
  { color: "#c2610f", dash: "6 4" },
  { color: "#0f8a6c", dash: "2 4" },
] as const;

export type TrendSeries<K extends string> = { key: K; label: string };
export type TrendRow<K extends string> = { year: number } & Record<K, number | null>;

export type ChartRow = TrendRow<"revenue" | "expenses" | "netAssets">;

const FINANCIAL_SERIES: TrendSeries<"revenue" | "expenses" | "netAssets">[] = [
  { key: "revenue", label: "總收入" },
  { key: "expenses", label: "總支出" },
  { key: "netAssets", label: "年底淨資產" },
];

const SURFACE = "#ffffff";


function niceMax(v: number): number {
  if (v <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * step >= v) return m * step;
  return 10 * step;
}

export function FinancialChart({ rows }: { rows: ChartRow[] }) {
  return (
    <TrendChart
      rows={rows}
      series={FINANCIAL_SERIES}
      label={`近 ${rows.length} 年總收入、總支出、年底淨資產折線圖，數字見下方表格`}
    />
  );
}

/** series 的順序決定顏色（第 1 條藍、第 2 條橘、第 3 條綠），呼叫端要固定順序、不要依金額排。 */
export function TrendChart<K extends string>({
  rows,
  series,
  label,
  partialYear,
  tooltipExtra,
}: {
  rows: TrendRow<K>[];
  series: (TrendSeries<K> & { styleIndex?: number })[];
  label: string;
  /** 還沒過完的年度（今年）：軸上寫「至今」，免得最後一年看起來是掉下來 */
  partialYear?: number;
  /** 提示框金額下方多一行補充（例：捐給幾個組織、幾筆） */
  tooltipExtra?: (year: number) => string;
}) {
  const SERIES = series.map((s, i) => ({ ...s, ...STYLES[s.styleIndex ?? i] }));
  type SeriesKey = K;
  const val = (r: TrendRow<K>, k: K): number | null => r[k] as number | null;
  const [hover, setHover] = useState<number | null>(null);
  const uid = useId().replace(/:/g, "");
  // 依實際寬度畫，不用 viewBox 整張縮放：手機上字才不會縮到看不見
  const ref = useRef<HTMLElement>(null);
  const [W, setW] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(280, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const narrow = W < 480;
  const H = narrow ? 220 : 260;
  const PAD = { top: 16, right: narrow ? 72 : 96, bottom: 32, left: narrow ? 52 : 64 };
  const data = [...rows].sort((a, b) => a.year - b.year);
  const values = data.flatMap((r) => SERIES.map((s) => val(r, s.key))).filter((v): v is number => v !== null);
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
      const v = val(data[i], s.key);
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
    <figure ref={ref} className="relative">
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
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        className="block"
        role="img"
        aria-label={label}
        onMouseLeave={() => setHover(null)}
      >
        {/* LK-50：線由左往右畫出來（用裁切框長出來，虛線樣式不受影響）；第一條線下方加很淡的漸層面積 */}
        <defs>
          <clipPath id={`${uid}-reveal`}>
            <rect
              x={0}
              y={0}
              width={W}
              height={H}
              className="animate-grow-x"
              style={{ transformBox: "fill-box", transformOrigin: "left", animationDuration: "1.4s" }}
            />
          </clipPath>
          {SERIES.map((s) => (
            <linearGradient key={s.key} id={`${uid}-area-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity="0.2" />
              <stop offset="100%" stopColor={s.color} stopOpacity="0" />
            </linearGradient>
          ))}
        </defs>
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
            {r.year === partialYear ? `${r.year} 至今` : `${r.year} 年`}
          </text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} stroke="#9ca2bf" strokeWidth="1" />}
        {SERIES.map((s, si) => {
          // 某一年沒有數字就斷線，不拿前後年硬連
          const segments: string[] = [];
          let cur: string[] = [];
          data.forEach((r, i) => {
            const v = val(r, s.key);
            if (v === null) {
              if (cur.length) segments.push(cur.join(" "));
              cur = [];
            } else cur.push(`${cur.length ? "L" : "M"}${x(i)},${y(v)}`);
          });
          if (cur.length) segments.push(cur.join(" "));
          const end = ends.find((e) => e?.key === s.key);
          const base = y(Math.max(minV, 0));
          const withArea = si === 0;
          return (
            <g key={s.key} clipPath={`url(#${uid}-reveal)`}>
              {withArea &&
                segments.map((d) => {
                  const xs = [...d.matchAll(/[ML]([\d.]+),/g)].map((m) => m[1]);
                  return (
                    <path
                      key={`area-${d}`}
                      d={`${d} L${xs[xs.length - 1]},${base} L${xs[0]},${base} Z`}
                      fill={`url(#${uid}-area-${s.key})`}
                    />
                  );
                })}
              {segments.map((d) => (
                <path key={d} d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash} />
              ))}
              {data.map((r, i) =>
                val(r, s.key) === null ? null : (
                  <circle
                    key={r.year}
                    cx={x(i)}
                    cy={y(val(r, s.key) as number)}
                    r={hover === i ? 5.5 : 4}
                    fill={s.color}
                    stroke={SURFACE}
                    strokeWidth="2"
                    className="animate-pop transition-[r] duration-150"
                    style={{ transformBox: "fill-box", transformOrigin: "center", animationDelay: `${0.25 + (i / Math.max(1, data.length - 1)) * 1.1}s` }}
                  />
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
          className="pointer-events-none absolute top-8 z-10 w-56 rounded-lg border border-ink-200 bg-white p-2.5 text-xs shadow-md"
          style={{
            left: `${(x(hover) / W) * 100}%`,
            transform: x(hover) > W / 2 ? "translateX(calc(-100% - 12px))" : "translateX(12px)",
          }}
          role="status"
        >
          <p className="mb-1 font-semibold text-ink-900">
            民國 {hovered.year} 年{hovered.year === partialYear && "（統計到目前）"}
          </p>
          <dl className="space-y-0.5">
            {SERIES.map((s) => (
              <div key={s.key} className="flex items-center justify-between gap-2">
                <dt className="flex items-center gap-1 whitespace-nowrap text-ink-600">
                  <span className="inline-block h-2 w-2 rounded-full" style={{ background: s.color }} aria-hidden />
                  {s.label}
                </dt>
                <dd className="font-num whitespace-nowrap tabular-nums text-ink-900">{formatMoney(val(hovered, s.key))}</dd>
              </div>
            ))}
          </dl>
          {tooltipExtra && <p className="mt-1 text-ink-600">{tooltipExtra(hovered.year)}</p>}
        </div>
      )}
    </figure>
  );
}

/** 捐款企業頁的近 5 年捐款趨勢（LK-38）：一條線、每年總額，提示框另寫捐給幾個組織、幾筆。
 *  放在這支 client 檔裡，因為提示框補充是函式，不能從 server component 傳過來。 */
export function DonorTrendChart({
  yearly,
  partialYear,
}: {
  yearly: { year: number; total: number; org_count: number; count: number }[];
  partialYear: number;
}) {
  const byYear = new Map(yearly.map((r) => [r.year, r]));
  return (
    <TrendChart
      rows={yearly.map((r) => ({ year: r.year, total: r.total }))}
      series={[{ key: "total", label: "捐款總額" }]}
      label={`近 ${yearly.length} 年每年捐款總額折線圖：${yearly.map((r) => `${r.year} 年 ${formatMoney(r.total)}`).join("、")}`}
      partialYear={partialYear}
      tooltipExtra={(y) => {
        const r = byYear.get(y);
        return r ? `捐給 ${r.org_count} 個組織，共 ${r.count} 筆` : "";
      }}
    />
  );
}
