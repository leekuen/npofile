import Link from "next/link";

import { formatMoney, formatNumber } from "@/lib/format";
import { ApiUnavailableError, listDonorGroups, listDonors, type DonorQuery } from "@/lib/server-api";
import type { DonorGroupRow, DonorSummaryRow, Page } from "@/lib/types";

import { Card, EmptyState, ErrorBox, Skeleton } from "./ui";

const PAGE_SIZE = 20;
const KINDS = [
  { value: "", label: "企業與團體" },
  { value: "company", label: "只看企業" },
  { value: "group", label: "只看團體" },
];

type Search = Record<string, string | string[] | undefined>;

function pick(sp: Search, key: string) {
  const v = sp[key];
  return (Array.isArray(v) ? v[0] : v)?.trim() ?? "";
}

type Query = DonorQuery & { view?: string };

function href(query: Query, patch: Partial<Query>) {
  const next = { ...query, ...patch };
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(next)) {
    if (!v || (k === "page" && v === "1")) continue;
    params.set(k, v);
  }
  const s = params.toString();
  return s ? `/donors?${s}` : "/donors";
}

const inputCls =
  "w-full rounded-xl border border-ink-300 bg-white px-3 py-2 text-sm text-ink-900 focus:border-brand-600 focus:outline-none";

export async function DonorSearch({ searchParams }: { searchParams: Promise<Search> }) {
  const sp = await searchParams;
  const byGroup = pick(sp, "view") === "group";
  const query: Query = {
    q: pick(sp, "q"),
    kind: byGroup ? "" : pick(sp, "kind"),
    page: pick(sp, "page") || "1",
    view: byGroup ? "group" : "",
  };

  let page: Page<DonorSummaryRow> | Page<DonorGroupRow>;
  try {
    page = byGroup ? await listDonorGroups({ q: query.q, page: query.page }) : await listDonors(query);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前查不到捐款人資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }

  const chips = [
    query.q && { label: `關鍵字：${query.q}`, clear: { q: "" } },
    query.kind && { label: KINDS.find((k) => k.value === query.kind)?.label ?? query.kind, clear: { kind: "" } },
  ].filter(Boolean) as { label: string; clear: Partial<Query> }[];

  const current = Number(query.page) || 1;
  const lastPage = Math.max(1, Math.ceil(page.count / PAGE_SIZE));
  const rankBase = (current - 1) * PAGE_SIZE;

  return (
    <section className="space-y-4" aria-label="捐款企業列表">
      <Card>
        <nav aria-label="排行方式" className="mb-4 inline-flex rounded-xl border border-ink-300 bg-ink-50 p-1 text-sm">
          {[
            { label: "依公司", active: !byGroup, to: href(query, { view: "", page: "1" }) },
            { label: "依集團", active: byGroup, to: href(query, { view: "group", kind: "", page: "1" }) },
          ].map((t) => (
            <Link
              key={t.label}
              href={t.to}
              aria-current={t.active ? "page" : undefined}
              className={`rounded-lg px-4 py-1.5 font-medium ${t.active ? "bg-white text-brand-900 shadow-sm" : "text-ink-700 hover:text-ink-900"}`}
            >
              {t.label}
            </Link>
          ))}
        </nav>
        <form
          action="/donors"
          method="get"
          className={`grid gap-3 sm:items-end ${byGroup ? "sm:grid-cols-[1fr_auto]" : "sm:grid-cols-[2fr_1fr_auto]"}`}
        >
          {byGroup && <input type="hidden" name="view" value="group" />}
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-ink-700">
              {byGroup ? "集團或旗下公司名稱、統一編號" : "企業或團體名稱、統一編號"}
            </span>
            <input
              type="search"
              name="q"
              defaultValue={query.q}
              placeholder={byGroup ? "例：富邦、國泰" : "例：銀行、22099131"}
              className={inputCls}
            />
          </label>
          {!byGroup && (
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-ink-700">類型</span>
            <select name="kind" defaultValue={query.kind} className={inputCls}>
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          )}
          <button type="submit" className="h-10 rounded-xl bg-brand-700 px-5 text-sm font-semibold text-white hover:bg-brand-800">
            查詢
          </button>
        </form>
      </Card>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-700">
          共 <strong className="tabular-nums">{formatNumber(page.count)}</strong> {byGroup ? "個集團，依旗下公司捐款合計排序" : "個，依捐款總額排序"}
        </span>
        {chips.map((c) => (
          <Link
            key={c.label}
            href={href(query, { ...c.clear, page: "1" })}
            className="inline-flex items-center gap-1 rounded-full border border-ink-300 bg-white px-3 py-1 text-ink-800 hover:bg-ink-100"
            aria-label={`移除條件：${c.label}`}
          >
            {c.label}
            <span aria-hidden className="text-ink-500">
              ×
            </span>
          </Link>
        ))}
      </div>

      {byGroup && (
        <p className="text-xs text-ink-600">
          依經濟部商工登記的董監事歸戶：兩家以上捐款公司的董監事由同一家公司出任，就算同一個集團。只表示有這層關係，不代表持股比例或誰控制誰。
        </p>
      )}

      {page.results.length === 0 ? (
        <EmptyState title={byGroup ? "找不到符合條件的集團" : "找不到符合條件的企業或團體"}>
          換個關鍵字，或移除上面的條件再試一次。
        </EmptyState>
      ) : byGroup ? (
        <ol className="divide-y divide-ink-200 overflow-hidden rounded-2xl border border-ink-200 bg-white">
          {(page.results as DonorGroupRow[]).map((g, i) => (
            <li key={g.id}>
              <Link href={`/donors/groups/${g.id}`} className="group flex items-center gap-3 px-4 py-3 hover:bg-ink-50">
                <span className="w-8 shrink-0 text-right font-semibold tabular-nums text-ink-500">{rankBase + i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="break-words font-semibold text-brand-900 underline-offset-2 group-hover:underline">{g.label}</p>
                  <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-ink-600">
                    <span className="rounded bg-ink-100 px-1.5 text-ink-700">集團</span>
                    <span>捐給 {formatNumber(g.org_count)} 個組織</span>
                  </p>
                </div>
                <span className="shrink-0 text-right font-semibold tabular-nums text-ink-900">{formatMoney(g.total)}</span>
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <ol className="divide-y divide-ink-200 overflow-hidden rounded-2xl border border-ink-200 bg-white">
          {(page.results as DonorSummaryRow[]).map((d, i) => (
            <li key={d.id}>
              <Link href={`/donors/${d.id}`} className="group flex items-center gap-3 px-4 py-3 hover:bg-ink-50">
                <span className="w-8 shrink-0 text-right font-semibold tabular-nums text-ink-500">{rankBase + i + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="break-words font-semibold text-brand-900 underline-offset-2 group-hover:underline">{d.name}</p>
                  <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-ink-600">
                    <span className="rounded bg-ink-100 px-1.5 text-ink-700">{d.kind_label}</span>
                    {d.ubn && <span className="tabular-nums">統編 {d.ubn}</span>}
                    <span>捐給 {formatNumber(d.org_count)} 個組織</span>
                  </p>
                </div>
                <span className="shrink-0 text-right font-semibold tabular-nums text-ink-900">{formatMoney(d.total)}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}

      {lastPage > 1 && (
        <nav aria-label="分頁" className="flex items-center justify-between text-sm">
          {current > 1 ? (
            <Link href={href(query, { page: String(current - 1) })} className="rounded-xl border border-ink-300 bg-white px-4 py-2 hover:bg-ink-50">
              ‹ 上一頁
            </Link>
          ) : (
            <span />
          )}
          <span className="tabular-nums text-ink-600">
            第 {formatNumber(current)} / {formatNumber(lastPage)} 頁
          </span>
          {current < lastPage ? (
            <Link href={href(query, { page: String(current + 1) })} className="rounded-xl border border-ink-300 bg-white px-4 py-2 hover:bg-ink-50">
              下一頁 ›
            </Link>
          ) : (
            <span />
          )}
        </nav>
      )}
    </section>
  );
}

export function DonorSearchSkeleton() {
  return (
    <div className="space-y-4">
      <Card>
        <Skeleton className="h-10 w-full" />
      </Card>
      <div className="space-y-px overflow-hidden rounded-2xl border border-ink-200 bg-white">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="h-4 w-6" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-3 w-1/3" />
            </div>
            <Skeleton className="h-4 w-20" />
          </div>
        ))}
      </div>
    </div>
  );
}
