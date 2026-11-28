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
          <span className="sr-only">近 5 年受裁罰 </span>
          {count} 次
        </>
      ) : (
        <>近 5 年受裁罰 {count} 次</>
      )}
    </span>
  );
}

/** 揭露指數的圓環顏色：只分「揭露得多／中等／少」，不做好壞評等 */
export function scoreStroke(score: number) {
  if (score >= 70) return "stroke-brand-600";
  if (score >= 40) return "stroke-brand-400";
  return "stroke-ink-400";
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
        <circle cx="20" cy="20" r={r} fill="none" strokeWidth={lg ? 3.5 : 4} className="stroke-ink-200" />
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
        <span className={`font-num font-semibold tabular-nums text-ink-900 ${lg ? "text-3xl" : "text-sm"}`}>{score}</span>
        {lg && <span className="mt-1 text-xs text-ink-500">／100</span>}
      </span>
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`surface p-4 sm:p-5 ${className}`}>{children}</div>;
}

/** 頁面頂端：麵包屑（選用）＋大標＋一句說明（選用）＋右側區塊（選用）。全站頁首長同一個樣子。 */
export function PageHeader({
  crumbs,
  title,
  description,
  aside,
  children,
}: {
  crumbs?: { href?: string; label: string }[];
  title: ReactNode;
  description?: ReactNode;
  aside?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="space-y-3">
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="位置" className="flex flex-wrap items-center gap-x-1.5 text-sm text-ink-600">
          {crumbs.map((c, i) => (
            <span key={`${c.label}-${i}`} className="inline-flex items-center gap-x-1.5">
              {i > 0 && (
                <span aria-hidden className="text-ink-400">
                  /
                </span>
              )}
              {c.href ? (
                <Link href={c.href} className="rounded text-ink-600 underline-offset-2 hover:text-brand-800 hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span>{c.label}</span>
              )}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 flex-1 space-y-2">
          <h1 className="font-display text-2xl font-extrabold text-balance break-words text-ink-900 sm:text-[2rem] sm:leading-tight">
            {title}
          </h1>
          {description && <div className="max-w-2xl text-ink-700">{description}</div>}
          {children}
        </div>
        {aside}
      </div>
    </header>
  );
}

/** 數字格：上面小字標籤、下面大數字。tone="alert" 用在裁罰這種要被注意的數字。 */
export function Stat({
  label,
  value,
  tone = "default",
  className = "",
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: "default" | "alert";
  className?: string;
}) {
  return (
    <div className={`surface px-4 py-3 ${className}`}>
      <dt className="text-xs text-ink-600">{label}</dt>
      <dd
        className={`mt-1 font-num text-lg font-semibold tabular-nums sm:text-xl ${tone === "alert" ? "text-red-700" : "text-ink-900"}`}
      >
        {value}
      </dd>
    </div>
  );
}

/** 區塊標題（h2）：全站同一個字級與間距 */
export function SectionHeading({ id, children, className = "" }: { id?: string; children: ReactNode; className?: string }) {
  return (
    <h2 id={id} className={`font-display text-xl font-bold text-ink-900 ${className}`}>
      {children}
    </h2>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-ink-300 bg-white/60 px-4 py-10 text-center">
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
