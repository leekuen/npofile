import Link from "next/link";
import { type ReactNode, Suspense } from "react";

import { formatCompact, formatMoney, formatNumber } from "@/lib/format";
import { ApiUnavailableError, getFilters, getTaxonomy, listOrgs, type OrgQuery } from "@/lib/server-api";

import { CategoryBrowser, CategoryChip } from "./categories";
import { FieldPicksSection, HomeDiscover, HomeSectionSkeleton } from "./home-discover";
import { EmptyState, ErrorBox, PenaltyBadge, ScoreBadge, Skeleton, StatusBadge } from "./ui";

const PAGE_SIZE = 20;

/** 列表的欄：指數｜組織｜近 5 年公開募款｜裁罰｜狀態｜箭頭（狀態欄從 md 起；手機只留指數、組織、箭頭） */
const ROW =
  "grid-cols-[3rem_minmax(0,1fr)_1rem] items-center gap-3 px-4 sm:grid-cols-[3rem_minmax(0,1fr)_8.5rem_5.5rem_1rem] md:grid-cols-[3rem_minmax(0,1fr)_9rem_6rem_6rem_1rem]";
const DEFAULT_ORDERING = "raised";
const ORDERINGS = [
  { value: "raised", label: "依近 5 年公開募款排序" },
  { value: "score", label: "依揭露指數排序" },
  { value: "name", label: "依名稱排序" },
];

type Search = Record<string, string | string[] | undefined>;

function pick(sp: Search, key: string) {
  const v = sp[key];
  return (Array.isArray(v) ? v[0] : v)?.trim() ?? "";
}

function href(query: OrgQuery, patch: Partial<OrgQuery>) {
  const next = { ...query, ...patch };
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(next)) {
    if (!v || (k === "ordering" && v === DEFAULT_ORDERING) || (k === "page" && v === "1")) continue;
    params.set(k, v);
  }
  const s = params.toString();
  return s ? `/?${s}` : "/";
}

const selectCls =
  "w-full truncate rounded-xl border border-ink-300 bg-white px-3 py-2.5 text-sm text-ink-900 hover:border-ink-400 focus:border-brand-600 focus:outline-none";

export async function OrgSearch({ searchParams, stats }: { searchParams: Promise<Search>; stats?: ReactNode }) {
  const sp = await searchParams;
  const query: OrgQuery = {
    q: pick(sp, "q"),
    city: pick(sp, "city"),
    status: pick(sp, "status"),
    ordering: pick(sp, "ordering") || DEFAULT_ORDERING,
    field: pick(sp, "field"),
    sub: pick(sp, "sub"),
    target: pick(sp, "target"),
    page: pick(sp, "page") || "1",
  };

  let filters, page, taxonomy;
  try {
    [filters, page, taxonomy] = await Promise.all([getFilters(), listOrgs(query), getTaxonomy()]);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前查不到組織資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }

  const statusLabel = Object.fromEntries(filters.statuses.map((s) => [s.value, s.label]));
  const fieldNode = taxonomy.fields.find((f) => f.code === query.field);
  const subNode = fieldNode?.subs.find((s) => s.code === query.sub);
  const targetNode = taxonomy.targets.find((t) => t.code === query.target);
  const chips = [
    query.q && { label: `關鍵字：${query.q}`, clear: { q: "" } },
    fieldNode && { label: fieldNode.label, clear: { field: "", sub: "" } },
    subNode && { label: `${fieldNode!.label} › ${subNode.label}`, clear: { sub: "" } },
    targetNode && { label: `服務對象：${targetNode.label}`, clear: { target: "" } },
    query.city && { label: query.city, clear: { city: "" } },
    query.status && { label: statusLabel[query.status] ?? query.status, clear: { status: "" } },
  ].filter(Boolean) as { label: string; clear: Partial<OrgQuery> }[];

  const current = Number(query.page) || 1;
  const lastPage = Math.max(1, Math.ceil(page.count / PAGE_SIZE));
  // 探索區：什麼條件都沒有、在第 1 頁（改排序不算條件）；領域區：選了領域或服務對象、沒有關鍵字、在第 1 頁（LK-18）
  const showDiscover = current === 1 && !query.q && !query.city && !query.status && !query.field && !query.sub && !query.target;
  const showPicks = current === 1 && !query.q && Boolean(query.field || query.sub || query.target);

  return (
    <div className="space-y-8">
      <section
        aria-labelledby="search-title"
        className="surface relative isolate grid gap-6 overflow-hidden p-5 sm:p-8 lg:grid-cols-[minmax(0,1fr)_14rem] lg:items-stretch lg:gap-10 lg:p-10"
      >
        {/* 淡淡的靛藍＋暖黃光暈，只當背景，不放任何資訊 */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(60rem_24rem_at_0%_0%,var(--color-brand-50),transparent_60%),radial-gradient(28rem_18rem_at_100%_0%,var(--color-sun-50),transparent_70%)]"
        />
        <div className="min-w-0 space-y-5">
        <h1 id="search-title" className="font-display max-w-2xl text-3xl leading-tight font-extrabold text-balance text-ink-900 sm:text-[2.5rem]">
          查一個非營利組織的募款與裁罰紀錄
        </h1>
        <form
          key={`${query.q}|${query.city}|${query.status}|${query.ordering}|${query.field}|${query.sub}|${query.target}`}
          action="/"
          method="get"
          className="space-y-3"
        >
          {query.field && <input type="hidden" name="field" value={query.field} />}
          {query.sub && <input type="hidden" name="sub" value={query.sub} />}
          <div className="flex">
            <label htmlFor="org-q" className="sr-only">
              組織名稱或統一編號
            </label>
            <input
              id="org-q"
              type="search"
              name="q"
              defaultValue={query.q}
              placeholder="組織名稱或統一編號"
              className="min-w-0 flex-1 rounded-l-xl border-2 border-r-0 border-ink-900 bg-white px-4 py-3 text-base text-ink-900 placeholder:text-ink-500 focus:border-brand-700 focus:outline-none sm:py-3.5 sm:text-lg"
            />
            <button
              type="submit"
              className="shrink-0 rounded-r-xl border-2 border-l-0 border-ink-900 bg-sun-400 px-6 text-base font-bold text-ink-900 transition-colors hover:bg-sun-500 sm:px-8"
            >
              搜尋
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:gap-3 md:grid-cols-[repeat(3,minmax(0,1fr))_minmax(0,1.4fr)]">
            <label className="text-sm">
              <span className="sr-only">縣市</span>
              <select name="city" defaultValue={query.city} className={selectCls}>
                <option value="">全部縣市</option>
                {filters.cities.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="sr-only">營運狀態</span>
              <select name="status" defaultValue={query.status} className={selectCls}>
                <option value="">全部營運狀態</option>
                {filters.statuses.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="sr-only">服務對象</span>
              <select name="target" defaultValue={query.target} className={selectCls}>
                <option value="">全部服務對象</option>
                {taxonomy.targets.map((t) => (
                  <option key={t.code} value={t.code}>
                    {t.label}（{formatNumber(t.count)}）
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              <span className="sr-only">排序</span>
              <select name="ordering" defaultValue={query.ordering} className={selectCls}>
                {ORDERINGS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </form>
        <CategoryBrowser
          taxonomy={taxonomy}
          field={query.field ?? ""}
          sub={query.sub ?? ""}
          hrefFor={(patch) => href(query, { ...patch, page: "1" })}
        />
        </div>
        {stats}
      </section>

      {showDiscover && (
        <Suspense fallback={<HomeSectionSkeleton />}>
          <HomeDiscover />
        </Suspense>
      )}
      {showPicks && (
        <Suspense key={`${query.field}|${query.sub}|${query.target}|${query.city}|${query.status}`} fallback={<HomeSectionSkeleton />}>
          <FieldPicksSection query={query} />
        </Suspense>
      )}

      <section aria-labelledby="org-list-title" className="space-y-4">
      <h2 id="org-list-title" className="sr-only">
        組織列表
      </h2>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="mr-1 text-ink-700">
          共 <strong className="tabular-nums">{formatNumber(page.count)}</strong> 個組織
        </span>
        {chips.map((c) => (
          <Link
            key={c.label}
            href={href(query, { ...c.clear, page: "1" })}
            className="inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-brand-900 hover:border-brand-400"
            aria-label={`移除條件：${c.label}`}
          >
            {c.label}
            <span aria-hidden className="text-ink-500">
              ×
            </span>
          </Link>
        ))}
      </div>

      {page.results.length === 0 ? (
        <EmptyState title="找不到符合條件的組織">
          換個關鍵字，或移除上面的條件再試一次。
        </EmptyState>
      ) : (
        <div className="overflow-hidden surface">
          <div aria-hidden className={`${ROW} hidden border-b border-ink-200 bg-ink-50/70 py-2.5 text-xs font-medium text-ink-600 sm:grid`}>
            <span className="text-center">指數</span>
            <span>組織</span>
            <span className="text-right">近 5 年公開募款</span>
            <span>近 5 年裁罰</span>
            <span className="hidden md:block">營運狀態</span>
            <span />
          </div>
          <ul className="divide-y divide-ink-100">
            {page.results.map((org) => (
              <li key={org.ubn}>
                <Link href={`/orgs/${org.ubn}`} className={`group ${ROW} grid py-3.5 transition-colors hover:bg-brand-50/50`}>
                  <ScoreBadge score={org.disclosure_score} />
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-brand-900 underline-offset-2 group-hover:underline">{org.name}</p>
                    <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-600">
                      <span className="tabular-nums">統編 {org.ubn}</span>
                      {org.city && <span>{org.city}</span>}
                      {org.org_type && <span>{org.org_type}</span>}
                      {org.public_raised_5y > 0 && (
                        <span className="tabular-nums sm:hidden">近 5 年公開募款 {formatMoney(org.public_raised_5y)}</span>
                      )}
                      {org.latest_revenue && (
                        <span className="tabular-nums">
                          總收入 {formatCompact(org.latest_revenue.total_revenue)}（{org.latest_revenue.year} 年度）
                        </span>
                      )}
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1 md:hidden">
                        <StatusBadge status={org.status} label={org.status_label} />
                        <span className="sm:hidden">
                          <PenaltyBadge count={org.penalty_count_5y} />
                        </span>
                      </span>
                    </p>
                    {org.tags.length > 0 && (
                      <p className="mt-1.5 flex flex-wrap gap-1">
                        {org.tags.map((t) => (
                          <CategoryChip key={t.code} tag={t} link={false} />
                        ))}
                      </p>
                    )}
                  </div>
                  <span className="hidden text-right font-num text-sm whitespace-nowrap tabular-nums sm:block">
                    {org.public_raised_5y > 0 ? formatMoney(org.public_raised_5y) : <span className="text-ink-400">—</span>}
                  </span>
                  <span className="hidden text-sm sm:block">
                    {org.penalty_count_5y > 0 ? (
                      <PenaltyBadge count={org.penalty_count_5y} short />
                    ) : (
                      <span className="text-ink-500">無</span>
                    )}
                  </span>
                  <span className="hidden md:block">
                    <StatusBadge status={org.status} label={org.status_label} />
                  </span>
                  <span aria-hidden className="text-ink-400 transition-transform group-hover:translate-x-0.5 group-hover:text-brand-700">
                    ›
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {lastPage > 1 && (
        <nav aria-label="分頁" className="flex items-center justify-between text-sm">
          {current > 1 ? (
            <Link href={href(query, { page: String(current - 1) })} className="surface px-4 py-2 font-medium text-ink-800 hover:text-brand-800">
              ‹ 上一頁
            </Link>
          ) : (
            <span />
          )}
          <span className="tabular-nums text-ink-600">
            第 {formatNumber(current)} / {formatNumber(lastPage)} 頁
          </span>
          {current < lastPage ? (
            <Link href={href(query, { page: String(current + 1) })} className="surface px-4 py-2 font-medium text-ink-800 hover:text-brand-800">
              下一頁 ›
            </Link>
          ) : (
            <span />
          )}
        </nav>
      )}
      </section>
    </div>
  );
}

export function OrgSearchSkeleton() {
  return (
    <div className="space-y-8">
      <div className="surface space-y-5 p-5 sm:p-8">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-12 w-full max-w-3xl" />
        <Skeleton className="h-9 w-full max-w-xl" />
      </div>
      <div className="space-y-px overflow-hidden surface">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="h-12 w-12 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
