import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { formatMoney, formatNumber, formatRocDate } from "@/lib/format";
import { ApiUnavailableError, getCategory } from "@/lib/server-api";
import type { CategoryOverview } from "@/lib/types";

import { Card, EmptyState, ErrorBox, ScoreBadge, Skeleton, TextLink } from "./ui";

function listHref(c: CategoryOverview) {
  if (c.dimension === "target") return `/?target=${c.code}`;
  return c.parent ? `/?field=${c.parent.code}&sub=${c.code}` : `/?field=${c.code}`;
}

export async function CategoryOverviewView({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  let c: CategoryOverview | null;
  try {
    c = await getCategory(decodeURIComponent(code));
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前讀不到這個分類的資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  if (!c) notFound();

  return (
    <div className="space-y-8">
      <nav className="flex flex-wrap gap-x-2 text-sm text-ink-600" aria-label="位置">
        <TextLink href="/">首頁</TextLink>
        <span aria-hidden>›</span>
        {c.dimension === "target" ? (
          <span>服務對象</span>
        ) : c.parent ? (
          <TextLink href={`/categories/${c.parent.code}`}>{c.parent.label}</TextLink>
        ) : (
          <span>領域</span>
        )}
      </nav>

      <header className="space-y-4">
        <h1 className="font-display text-3xl font-extrabold text-ink-900">
          {c.dimension === "target" ? `服務${c.label}的組織` : c.label}
        </h1>
        <dl className="grid grid-cols-3 gap-2 sm:max-w-2xl sm:gap-3">
          <Stat label="組織" value={formatNumber(c.org_count)} />
          <Stat label={`近 5 年實募（民國 ${c.since_roc_year} 年起）`} value={formatMoney(c.raised_5y)} />
          <Stat label="近五年受裁罰" value={formatNumber(c.penalized_5y)} alert={c.penalized_5y > 0} />
        </dl>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <Link href={listHref(c)} className="rounded-xl bg-brand-700 px-4 py-2 font-semibold text-white hover:bg-brand-800">
            看全部 {formatNumber(c.org_count)} 個組織
          </Link>
          {c.subs.length > 0 && (
            <span className="flex flex-wrap gap-x-3 gap-y-1">
              <span className="text-ink-600">細分：</span>
              {c.subs.map((s) => (
                <TextLink key={s.code} href={`/categories/${s.code}`}>
                  {s.label}
                </TextLink>
              ))}
            </span>
          )}
        </p>
        <p className="text-xs text-ink-600">分類依官方勸募用途與組織名稱推測，可能有誤。</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="揭露指數最高">
          {c.top_score.length === 0 ? (
            <EmptyState title="這個分類還沒有組織" />
          ) : (
            <OrgList rows={c.top_score.map((o) => ({ ...o, right: <ScoreBadge score={o.disclosure_score} /> }))} />
          )}
        </Section>
        <Section title={`近 5 年實募最多`}>
          {c.top_raised.length === 0 ? (
            <EmptyState title="近 5 年沒有公益勸募紀錄" />
          ) : (
            <OrgList
              rows={c.top_raised.map((o) => ({ ...o, right: <span className="tabular-nums">{formatMoney(o.raised_5y)}</span> }))}
            />
          )}
        </Section>
      </div>

      <Section title="支持這個分類最多的企業與團體">
        {c.top_donors.length === 0 ? (
          <EmptyState title="還沒有收錄到這個分類的捐贈人清冊" />
        ) : (
          <Card className="p-0 sm:p-0">
            <ol className="divide-y divide-ink-100">
              {c.top_donors.map((d, i) => (
                <li key={d.donor_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                  <span className="w-6 text-right font-semibold tabular-nums text-ink-500">{i + 1}</span>
                  <span className="min-w-0 flex-1 break-words">
                    <TextLink href={`/donors/${d.donor_id}`}>{d.name}</TextLink>
                    <span className="ml-2 inline-block rounded bg-ink-100 px-1.5 text-xs text-ink-700">{d.kind_label}</span>
                    <span className="ml-2 text-xs text-ink-500">捐給 {formatNumber(d.org_count)} 個組織</span>
                  </span>
                  <span className="font-medium tabular-nums">{formatMoney(d.total)}</span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </Section>

      <Section title={`裁罰紀錄（所有年度，共 ${formatNumber(c.penalty_total)} 筆）`}>
        {c.penalties.length === 0 ? (
          <EmptyState title="這個分類沒有收錄到裁罰紀錄" />
        ) : (
          <ul className="space-y-3">
            {c.penalties.map((p) => (
              <li key={p.id}>
                <Card className="border-l-4 border-l-red-600">
                  <p className="flex flex-wrap items-baseline gap-x-3 text-sm">
                    <span className="font-semibold tabular-nums text-red-900">{formatRocDate(p.decided_on)}</span>
                    <TextLink href={`/orgs/${p.org_ubn}?tab=penalties`}>{p.org_name}</TextLink>
                  </p>
                  <p className="mt-1 text-sm break-words text-ink-800">{p.content}</p>
                  {p.fine_text && <p className="mt-1 text-xs text-ink-600">{p.fine_text}</p>}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}

function Stat({ label, value, alert = false }: { label: string; value: string; alert?: boolean }) {
  return (
    <Card className="p-3">
      <dt className="text-xs text-ink-600">{label}</dt>
      <dd className={`mt-1 text-base font-bold tabular-nums sm:text-xl ${alert ? "text-red-800" : "text-ink-900"}`}>{value}</dd>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="mb-3 font-display text-xl font-bold text-ink-900">{title}</h2>
      {children}
    </section>
  );
}

function OrgList({ rows }: { rows: { ubn: string; name: string; city: string; right: ReactNode }[] }) {
  return (
    <Card className="p-0 sm:p-0">
      <ol className="divide-y divide-ink-100">
        {rows.map((o, i) => (
          <li key={o.ubn} className="flex items-center gap-3 px-4 py-2.5 text-sm">
            <span className="w-5 text-right font-semibold tabular-nums text-ink-500">{i + 1}</span>
            <span className="min-w-0 flex-1 break-words">
              <TextLink href={`/orgs/${o.ubn}`}>{o.name}</TextLink>
              {o.city && <span className="ml-2 text-xs text-ink-500">{o.city}</span>}
            </span>
            {o.right}
          </li>
        ))}
      </ol>
    </Card>
  );
}

export function CategoryOverviewSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-9 w-1/2" />
      <Skeleton className="h-20 w-full max-w-2xl" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-64 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  );
}
