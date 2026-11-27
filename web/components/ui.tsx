import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import type { OrgStatus } from "@/lib/types";

/** 全站唯一的文字連結長相：連結色＋底線。外部網址自動開新分頁。 */
export function TextLink({ href, children, className = "", ...rest }: ComponentProps<typeof Link>) {
  const external = typeof href === "string" && /^https?:\/\//.test(href);
  const cls = `text-teal-800 underline underline-offset-2 hover:text-teal-950 ${className}`;
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={cls}>
        {children}
        <span className="sr-only">（另開新視窗）</span>
      </a>
    );
  }
  return (
    <Link href={href} className={cls} {...rest}>
      {children}
    </Link>
  );
}

const STATUS_STYLE: Record<OrgStatus, string> = {
  active: "bg-emerald-50 text-emerald-800 ring-emerald-600/30",
  cancelled: "bg-slate-100 text-slate-700 ring-slate-500/30",
  revoked: "bg-slate-100 text-slate-700 ring-slate-500/30",
  closed: "bg-amber-50 text-amber-900 ring-amber-600/30",
};

export function StatusBadge({ status, label }: { status: OrgStatus; label: string }) {
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[status]}`}>
      {label}
    </span>
  );
}

export function PenaltyBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-800 ring-1 ring-inset ring-red-600/30">
      <span aria-hidden>⚠</span>近五年受裁罰 {count} 次
    </span>
  );
}

/** 揭露指數的圓環顏色：只分「揭露得多／中等／少」，不做好壞評等 */
export function scoreStroke(score: number) {
  if (score >= 70) return "stroke-teal-600";
  if (score >= 40) return "stroke-teal-400";
  return "stroke-slate-400";
}

/** 揭露指數圓環：環的長度＝分數，中間是數字 */
export function ScoreBadge({ score, size = "sm" }: { score: number; size?: "sm" | "lg" }) {
  const lg = size === "lg";
  const r = 16;
  const c = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(100, score));
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center ${lg ? "h-24 w-24" : "h-12 w-12"}`}
      title={`揭露指數 ${score} 分（滿分 100）`}
    >
      <svg viewBox="0 0 40 40" className="absolute inset-0 -rotate-90" aria-hidden>
        <circle cx="20" cy="20" r={r} fill="none" strokeWidth={lg ? 3.5 : 4} className="stroke-slate-200" />
        <circle
          cx="20"
          cy="20"
          r={r}
          fill="none"
          strokeWidth={lg ? 3.5 : 4}
          strokeLinecap="round"
          strokeDasharray={`${(pct / 100) * c} ${c}`}
          className={scoreStroke(score)}
        />
      </svg>
      <span className="relative flex flex-col items-center leading-none">
        <span className={`font-bold tabular-nums text-slate-900 ${lg ? "text-3xl" : "text-sm"}`}>{score}</span>
        {lg && <span className="mt-1 text-xs text-slate-500">／100</span>}
      </span>
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-slate-200 bg-white p-4 sm:p-5 ${className}`}>{children}</div>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center">
      <p className="font-medium text-slate-800">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-600">{children}</div>}
    </div>
  );
}

export function ErrorBox({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div role="alert" className="rounded-lg border border-red-300 bg-red-50 px-4 py-4 text-red-900">
      <p className="font-semibold">
        <span aria-hidden>⚠ </span>
        {title}
      </p>
      {children && <div className="mt-1 text-sm">{children}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 ${className}`} aria-hidden />;
}

export function SourceNote({ name, url }: { name: string; url: string }) {
  if (!name && !url) return null;
  return (
    <span className="text-xs text-slate-600">
      來源：{url ? <TextLink href={url}>{name || "原始資料"}</TextLink> : name}
    </span>
  );
}
