import Link from "next/link";
import type { ComponentProps, CSSProperties, ReactNode } from "react";

import type { OrgStatus } from "@/lib/types";

/** LK-50：一組東西依序出現時，第 i 個晚一點（搭配 className="stagger animate-rise"） */
export function order(i: number): CSSProperties {
  return { "--i": i } as CSSProperties;
}

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

/** 揭露層級（LK-35；跟後端 orgs/scoring.py 的 LEVEL_MEDALS／LEVEL_NAMES 同一套）：
 * 給人看的是獎牌名稱，副標是這一級代表什麼 */
export const LEVEL_MEDALS = ["未分級", "銅", "銀", "金", "鑽石"] as const;
export const LEVEL_NAMES = ["資料不足", "身分可查", "活動可查", "財務可查", "長期可查"] as const;
export const MAX_LEVEL = 4;

const MEDAL_STYLES = [
  "bg-ink-50 text-ink-500 ring-ink-200",
  "bg-orange-100 text-orange-900 ring-orange-300",
  "bg-zinc-100 text-zinc-800 ring-zinc-400",
  "bg-amber-100 text-amber-900 ring-amber-400",
  "bg-sky-100 text-sky-900 ring-sky-400",
];

function clampLevel(level: number) {
  return Math.max(0, Math.min(MAX_LEVEL, level));
}

export function levelMedal(level: number) {
  return LEVEL_MEDALS[clampLevel(level)];
}

export function levelName(level: number) {
  return LEVEL_NAMES[clampLevel(level)];
}

/** 揭露層級徽章：獎牌名稱（顏色只是輔助，一定有字）；大尺寸再寫這一級代表什麼。只代表公開了多少，不做好壞評等 */
export function LevelBadge({ level, size = "sm" }: { level: number; size?: "sm" | "lg" }) {
  const lg = size === "lg";
  const n = clampLevel(level);
  return (
    <span className={`inline-flex shrink-0 items-center ${lg ? "gap-2" : ""}`} title={`揭露層級：${levelMedal(n)}（${levelName(n)}）`}>
      <span
        className={`inline-flex items-center justify-center whitespace-nowrap rounded-full font-semibold ring-1 ${MEDAL_STYLES[n]} ${n >= 3 ? "medal-sheen" : ""} ${
          lg ? "px-3 py-1 text-base" : "min-w-10 px-1.5 py-0.5 text-xs"
        }`}
      >
        <span className="sr-only">揭露層級 </span>
        {levelMedal(n)}
      </span>
      {lg && <span className="text-sm text-ink-700">{levelName(n)}</span>}
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
