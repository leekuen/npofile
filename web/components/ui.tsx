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

export function scoreTone(score: number) {
  if (score >= 70) return "bg-teal-700 text-white";
  if (score >= 40) return "bg-teal-100 text-teal-900";
  return "bg-slate-200 text-slate-800";
}

export function ScoreBadge({ score, size = "sm" }: { score: number; size?: "sm" | "lg" }) {
  const dims = size === "lg" ? "h-20 w-20 text-3xl" : "h-11 w-11 text-base";
  return (
    <span
      className={`inline-flex shrink-0 flex-col items-center justify-center rounded-full font-bold tabular-nums ${dims} ${scoreTone(score)}`}
      title={`揭露指數 ${score} 分（滿分 100）`}
    >
      {score}
      {size === "lg" && <span className="text-xs font-medium">／100</span>}
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
