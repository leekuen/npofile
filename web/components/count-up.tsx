"use client";

import { useEffect, useRef, useState } from "react";

import { formatCompact, formatMoney, formatNumber } from "@/lib/format";

const FORMATS = {
  number: (v: number) => formatNumber(Math.round(v)),
  money: (v: number) => formatMoney(Math.round(v)),
  compact: (v: number) => formatCompact(Math.round(v)),
} as const;

/** 數字進到畫面時由 0 數到最後的值（LK-50）。
 *  伺服器先輸出最後的值（螢幕報讀、搜尋引擎、沒有 JS 都讀得到）；
 *  數的過程只改畫面上的字，報讀用 aria-label 一直是最後的值。系統設定減少動態時不數。 */
export function CountUp({
  value,
  format = "number",
  duration = 1100,
  className = "",
}: {
  value: number;
  format?: keyof typeof FORMATS;
  duration?: number;
  className?: string;
}) {
  const fmt = FORMATS[format];
  const final = fmt(value);
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(final);
  const [pending, setPending] = useState(true);

  useEffect(() => {
    const el = ref.current;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!el || reduce || value === 0) {
      setPending(false);
      return;
    }
    let raf = 0;
    const run = () => {
      const start = performance.now();
      setPending(false);
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 4);
        setShown(fmt(value * eased));
        if (t < 1) raf = requestAnimationFrame(tick);
      };
      setShown(fmt(0));
      raf = requestAnimationFrame(tick);
    };
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          io.disconnect();
          run();
        }
      },
      { threshold: 0.3 },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
    // fmt 由 format 決定，format 不變就不用重跑
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, duration, format]);

  return (
    <span ref={ref} className={`${pending ? "countup-pending" : ""} ${className}`}>
      <span aria-hidden>{shown}</span>
      <span className="sr-only">{final}</span>
    </span>
  );
}
