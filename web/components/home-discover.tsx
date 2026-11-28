import Link from "next/link";

import { formatMoney, formatRocDate } from "@/lib/format";
import { ApiUnavailableError, getDiscover, getFieldPicks, type OrgQuery } from "@/lib/server-api";
import type { DiscoverEnding, DiscoverGift, DiscoverPenalty, FieldPickOrg } from "@/lib/types";

import { DiscoverTabs } from "./discover-tabs";
import { levelMedal, Skeleton } from "./ui";

const link = "text-brand-800 underline underline-offset-2 hover:text-brand-950";
const box = "surface animate-rise p-4 sm:p-6 [animation-delay:0.25s]";
/** 卡片一排：手機橫滑（露出下一張的邊，看得出可以滑），寬螢幕三欄 */
const cardRow = "-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 sm:mx-0 sm:grid sm:grid-cols-3 sm:overflow-visible sm:px-0 sm:pb-0";
const cardItem = "w-[78%] shrink-0 snap-start sm:w-auto";
const cardLink =
  "flex h-full flex-col gap-2 rounded-xl border border-ink-200 bg-white p-4 transition duration-200 hover:-translate-y-0.5 hover:border-brand-400 hover:shadow-[var(--shadow-card-hover)] motion-reduce:hover:translate-y-0";

function Empty({ children }: { children: string }) {
  return <p className="py-2 text-sm text-ink-600">{children}</p>;
}

function EndingCard({ e }: { e: DiscoverEnding }) {
  return (
    <Link href={`/orgs/${e.org_ubn}?tab=projects#p-${e.project_id}`} className={cardLink}>
      <span className="self-start rounded-full bg-sun-100 px-2.5 py-0.5 text-xs font-semibold text-ink-900">
        {e.days_left === 0 ? "今天截止" : `剩 ${e.days_left} 天`}
      </span>
      <span className="line-clamp-2 font-semibold text-ink-900">{e.name}</span>
      <span className="min-w-0">
        <span className="block truncate text-sm text-brand-900">{e.org_name}</span>
        <span className="text-xs tabular-nums text-ink-600">揭露層級 {levelMedal(e.org_level)}</span>
      </span>
      <span className="mt-auto text-sm tabular-nums text-ink-600">
        預募 {formatMoney(e.target)}・至 {formatRocDate(e.end_date)}
      </span>
    </Link>
  );
}

function PenaltyRow({ p }: { p: DiscoverPenalty }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-3 text-sm sm:grid-cols-[6.5rem_minmax(0,1fr)_minmax(0,13rem)_7rem] sm:items-baseline">
      <span className="col-span-2 text-xs tabular-nums text-ink-500 sm:col-span-1 sm:text-sm">{formatRocDate(p.decided_on)}</span>
      <Link href={`/orgs/${p.org_ubn}?tab=penalties`} className={`min-w-0 ${link}`}>
        {p.org_name}
      </Link>
      <span className="col-start-1 row-start-3 text-ink-700 sm:col-start-auto sm:row-start-auto">{p.kind}</span>
      <span className="text-right font-semibold whitespace-nowrap text-red-700">{p.fine_text.replace("罰鍰：", "罰鍰 ")}</span>
    </li>
  );
}

function GiftRow({ g }: { g: DiscoverGift }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-3 text-sm sm:grid-cols-[6.5rem_minmax(0,1fr)_9rem] sm:items-baseline">
      <span className="col-span-2 text-xs tabular-nums text-ink-500 sm:col-span-1 sm:text-sm">{formatRocDate(g.donated_on)}</span>
      <span className="min-w-0">
        <Link href={`/donors/${g.donor_id}`} className={link}>
          {g.donor_name}
        </Link>
        <span aria-hidden className="mx-1.5 text-ink-400">
          →
        </span>
        <span className="sr-only">捐給</span>
        <Link href={`/orgs/${g.org_ubn}`} className={link}>
          {g.org_name}
        </Link>
      </span>
      <span className="text-right font-semibold tabular-nums whitespace-nowrap text-ink-900">{formatMoney(g.amount)}</span>
    </li>
  );
}

/** 首頁探索區：沒有任何搜尋與篩選、在第 1 頁時才出現（由 OrgSearch 決定）。讀不到資料就整塊不出現，列表照常。 */
export async function HomeDiscover() {
  let data;
  try {
    data = await getDiscover();
  } catch (e) {
    if (e instanceof ApiUnavailableError) return null;
    throw e;
  }
  return (
    <section aria-label="探索" className={box}>
      <DiscoverTabs
        tabs={[
          {
            key: "ending",
            label: "快截止的募款",
            panel: data.ending.length ? (
              <ul className={cardRow}>
                {data.ending.map((e) => (
                  <li key={e.project_id} className={cardItem}>
                    <EndingCard e={e} />
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>最近 14 天沒有要截止的募款活動。</Empty>
            ),
          },
          {
            key: "penalties",
            label: "最新裁罰",
            panel: data.penalties.length ? (
              <ol className="divide-y divide-ink-100">
                {data.penalties.map((p, i) => (
                  <PenaltyRow key={`${p.org_ubn}-${p.decided_on}-${i}`} p={p} />
                ))}
              </ol>
            ) : (
              <Empty>還沒有裁罰紀錄。</Empty>
            ),
          },
          {
            key: "gifts",
            label: "企業捐款",
            panel: (
              <>
                {data.gifts.length ? (
                  <ul className="divide-y divide-ink-100">
                    {data.gifts.map((g) => (
                      <GiftRow key={`${g.donor_id}-${g.org_ubn}`} g={g} />
                    ))}
                  </ul>
                ) : (
                  <Empty>清冊上還沒有企業捐款。</Empty>
                )}
                <p className="mt-3 text-sm">
                  <Link href="/donors" className={link}>
                    看捐款企業排行
                  </Link>
                </p>
              </>
            ),
          },
        ]}
      />
    </section>
  );
}

function PickCard({ o }: { o: FieldPickOrg }) {
  const c = o.campaign;
  return (
    <Link href={`/orgs/${o.ubn}${c ? `?tab=projects#p-${c.project_id}` : ""}`} className={cardLink}>
      <span>
        <span className="block font-semibold text-brand-900">{o.name}</span>
        <span className="text-xs tabular-nums text-ink-600">
          {o.city ? `${o.city}・` : ""}揭露層級 {levelMedal(o.level)}
        </span>
      </span>
      {c ? (
        <>
          <span className="self-start rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-800">募款中</span>
          <span className="line-clamp-2 text-sm text-ink-800">{c.name}</span>
          <span className="mt-auto text-sm tabular-nums text-ink-600">
            預募 {formatMoney(c.target)}・至 {formatRocDate(c.end_date)}
          </span>
        </>
      ) : (
        <span className="mt-auto text-sm tabular-nums text-ink-600">近 5 年實募 {formatMoney(o.raised_5y)}</span>
      )}
    </Link>
  );
}

/** 首頁領域區：選了領域或服務對象、沒有關鍵字、在第 1 頁時出現（由 OrgSearch 決定）。 */
export async function FieldPicksSection({ query }: { query: OrgQuery }) {
  let picks;
  try {
    picks = await getFieldPicks(query);
  } catch (e) {
    if (e instanceof ApiUnavailableError) return null;
    throw e;
  }
  if (!picks) return null;
  return (
    <section aria-labelledby="picks-title" className={box}>
      <h2 id="picks-title" className="font-display text-lg font-bold text-balance text-ink-900 sm:text-xl">
        {picks.label}：近 5 年沒有受裁罰、有公益勸募紀錄的組織
      </h2>
      <p className="mt-1 text-sm text-ink-500">名稱看得出相關的排前面。揭露層級只看資料公開了多少，不代表本站背書。</p>
      {picks.orgs.length ? (
        <ul className={`mt-4 ${cardRow}`}>
          {picks.orgs.map((o) => (
            <li key={o.ubn} className={cardItem}>
              <PickCard o={o} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-ink-600">目前沒有符合條件的{picks.label}組織。</p>
      )}
    </section>
  );
}

export function HomeSectionSkeleton() {
  return (
    <div className={box} aria-hidden>
      <Skeleton className="mb-4 h-6 w-64" />
      <div className="grid gap-3 sm:grid-cols-3">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    </div>
  );
}
