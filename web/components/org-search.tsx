import Link from "next/link";
import type { ReactNode } from "react";

import { formatNumber } from "@/lib/format";
import { ApiUnavailableError, getFilters, getTaxonomy, listOrgs, type OrgQuery } from "@/lib/server-api";

import { CategoryBrowser, CategoryChip } from "./categories";
import { EmptyState, ErrorBox, PenaltyBadge, ScoreBadge, Skeleton, StatusBadge } from "./ui";

const PAGE_SIZE = 20;
const ORDERINGS = [
  { value: "score", label: "揭露指數高到低" },
  { value: "name", label: "名稱" },
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
    if (!v || (k === "ordering" && v === "score") || (k === "page" && v === "1")) continue;
    params.set(k, v);
  }
  const s = params.toString();
  return s ? `/?${s}` : "/";
}

const selectCls =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-teal-600 focus:outline-none";

export async function OrgSearch({ searchParams, stats }: { searchParams: Promise<Search>; stats?: ReactNode }) {
  const sp = await searchParams;
  const query: OrgQuery = {
    q: pick(sp, "q"),
    city: pick(sp, "city"),
    status: pick(sp, "status"),
    ordering: pick(sp, "ordering") || "score",
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

  return (
    <div className="space-y-8">
      <section aria-labelledby="search-title" className="space-y-5 border-b border-slate-200 pb-8">
        <h1 id="search-title" className="max-w-2xl text-3xl font-bold tracking-tight text-balance text-slate-900 sm:text-4xl">
          查一個非營利組織的募款與裁罰紀錄
        </h1>
        <form
          key={`${query.q}|${query.city}|${query.status}|${query.ordering}|${query.field}|${query.sub}|${query.target}`}
          action="/"
          method="get"
          className="max-w-3xl space-y-3"
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
              className="min-w-0 flex-1 rounded-l-lg border-2 border-r-0 border-slate-800 bg-white px-4 py-3 text-base text-slate-900 placeholder:text-slate-500 focus:border-teal-700 focus:outline-none"
            />
            <button
              type="submit"
              className="shrink-0 rounded-r-lg bg-teal-700 px-6 text-base font-semibold text-white hover:bg-teal-800"
            >
              搜尋
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center sm:gap-3">
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
            <label className="flex items-center gap-2 text-sm">
              <span className="shrink-0 text-slate-600">排序</span>
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
        {stats}
      </section>

      <section aria-labelledby="org-list-title" className="space-y-4">
      <h2 id="org-list-title" className="sr-only">
        組織列表
      </h2>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-700">
          共 <strong className="tabular-nums">{formatNumber(page.count)}</strong> 個組織
        </span>
        {chips.map((c) => (
          <Link
            key={c.label}
            href={href(query, { ...c.clear, page: "1" })}
            className="inline-flex items-center gap-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-slate-800 hover:bg-slate-100"
            aria-label={`移除條件：${c.label}`}
          >
            {c.label}
            <span aria-hidden className="text-slate-500">
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
        <ul className="divide-y divide-slate-200 overflow-hidden rounded-lg border border-slate-200 bg-white">
          {page.results.map((org) => (
            <li key={org.ubn}>
              <Link href={`/orgs/${org.ubn}`} className="group flex items-center gap-3 px-4 py-3 hover:bg-slate-50">
                <ScoreBadge score={org.disclosure_score} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-semibold text-teal-900 underline-offset-2 group-hover:underline">{org.name}</p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-600">
                    <span className="tabular-nums">統編 {org.ubn}</span>
                    {org.city && <span>{org.city}</span>}
                    {org.org_type && <span>{org.org_type}</span>}
                    <StatusBadge status={org.status} label={org.status_label} />
                    <PenaltyBadge count={org.penalty_count_5y} />
                  </p>
                  {org.tags.length > 0 && (
                    <p className="mt-1.5 flex flex-wrap gap-1">
                      {org.tags.map((t) => (
                        <CategoryChip key={t.code} tag={t} link={false} />
                      ))}
                    </p>
                  )}
                </div>
                <span aria-hidden className="text-slate-400">
                  ›
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {lastPage > 1 && (
        <nav aria-label="分頁" className="flex items-center justify-between text-sm">
          {current > 1 ? (
            <Link href={href(query, { page: String(current - 1) })} className="rounded-md border border-slate-300 bg-white px-4 py-2 hover:bg-slate-50">
              ‹ 上一頁
            </Link>
          ) : (
            <span />
          )}
          <span className="tabular-nums text-slate-600">
            第 {formatNumber(current)} / {formatNumber(lastPage)} 頁
          </span>
          {current < lastPage ? (
            <Link href={href(query, { page: String(current + 1) })} className="rounded-md border border-slate-300 bg-white px-4 py-2 hover:bg-slate-50">
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
      <div className="space-y-5 border-b border-slate-200 pb-8">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-12 w-full max-w-3xl" />
        <Skeleton className="h-9 w-full max-w-xl" />
      </div>
      <div className="space-y-px overflow-hidden rounded-lg border border-slate-200 bg-white">
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
