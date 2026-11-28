import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import type { OrgStatus } from "@/lib/types";

/** 全站唯一的文字連結長相：連結色＋底線。外部網址自動開新分頁。 */
export function TextLink({ href, children, className = "", ...rest }: ComponentProps<typeof Link>) {
  const external = typeof href === "string" && /^https?:\/\//.test(href);
  const cls = `text-brand-800 underline underline-offset-2 hover:text-brand-950 ${className}`;
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
  cancelled: "bg-ink-100 text-ink-700 ring-ink-500/30",
  revoked: "bg-ink-100 text-ink-700 ring-ink-500/30",
  closed: "bg-amber-50 text-amber-900 ring-amber-600/30",
};

export function StatusBadge({ status, label }: { status: OrgStatus; label: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${STATUS_STYLE[status]}`}>
      {label}
    </span>
  );
}

export function PenaltyBadge({ count, short = false }: { count: number; short?: boolean }) {
  if (count <= 0) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap text-red-700">
      <span aria-hidden className="h-2 w-2 rounded-full bg-red-600" />
      {short ? (
        <>
          <span className="sr-only">近五年受裁罰 </span>
          {count} 次
        </>
      ) : (
        <>近五年受裁罰 {count} 次</>
      )}
    </span>
  );
}

/** 揭露層級的名稱（LK-35；跟後端 orgs/scoring.py 的 LEVEL_NAMES 同一套） */
export const LEVEL_NAMES = ["資料不足", "身分可查", "活動可查", "財務可查", "長期可查"] as const;
export const MAX_LEVEL = 4;

export function levelName(level: number) {
  return LEVEL_NAMES[Math.max(0, Math.min(MAX_LEVEL, level))];
}

/** 揭露層級：四格進度條＋「N／4」，大尺寸再寫名稱。只代表公開了多少，不做好壞評等 */
export function LevelBadge({ level, size = "sm" }: { level: number; size?: "sm" | "lg" }) {
  const lg = size === "lg";
  const n = Math.max(0, Math.min(MAX_LEVEL, level));
  return (
    <span
      className={`inline-flex shrink-0 flex-col ${lg ? "gap-1.5" : "w-12 gap-1"}`}
      title={`揭露層級 ${n}／${MAX_LEVEL}：${levelName(n)}`}
    >
      <span className={`flex ${lg ? "gap-1" : "gap-0.5"}`} aria-hidden>
        {Array.from({ length: MAX_LEVEL }, (_, i) => (
          <span
            key={i}
            className={`${lg ? "h-2.5 w-10" : "h-1.5 flex-1"} rounded-sm ${i < n ? "bg-brand-600" : "bg-ink-200"}`}
          />
        ))}
      </span>
      <span className={`font-num tabular-nums leading-none ${lg ? "text-sm text-ink-700" : "text-xs text-ink-700"}`}>
        <span className="sr-only">揭露層級 </span>
        {n}／{MAX_LEVEL}
        {lg && <span className="ml-1.5 font-sans font-semibold text-ink-900">{levelName(n)}</span>}
      </span>
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-ink-200 bg-white p-4 sm:p-5 ${className}`}>{children}</div>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-300 bg-white/60 px-4 py-8 text-center">
      <p className="font-medium text-ink-800">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-600">{children}</div>}
    </div>
  );
}

export function ErrorBox({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div role="alert" className="rounded-2xl border border-red-300 bg-red-50 px-4 py-4 text-red-900">
      <p className="font-semibold">
        <span aria-hidden>⚠ </span>
        {title}
      </p>
      {children && <div className="mt-1 text-sm">{children}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-ink-200 ${className}`} aria-hidden />;
}

export function SourceNote({ name, url }: { name: string; url: string }) {
  if (!name && !url) return null;
  return (
    <span className="text-xs text-ink-600">
      來源：{url ? <TextLink href={url}>{name || "原始資料"}</TextLink> : name}
    </span>
  );
}
