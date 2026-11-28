import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { formatCompact, formatDonationWhen, formatMoney, formatNumber, formatRocDate, shortSourceName } from "@/lib/format";
import { ApiUnavailableError, getDonor } from "@/lib/server-api";
import type { CompanyEsg, DonorDetail } from "@/lib/types";

import { DonorTrendChart } from "./financial-chart";
import { Card, ErrorBox, PageHeader, Skeleton, SourceNote, TextLink } from "./ui";

export async function DonorDetailView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let donor: DonorDetail | null;
  try {
    donor = await getDonor(id);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前讀不到這個捐款人的資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  if (!donor) notFound();

  const shown = donor.donations.length;
  const ov = donor.overview;

  return (
    <div className="space-y-8">
      <PageHeader
        crumbs={[{ href: "/donors", label: "捐款企業" }]}
        title={donor.name}
        aside={
          <Card className="w-full shrink-0 bg-gradient-to-br from-white to-brand-50/60 sm:w-72">
            <p className="text-sm text-ink-600">近 5 年清冊上的捐款總額</p>
            <p className="mt-1 font-num text-2xl font-bold tabular-nums text-ink-900">{formatMoney(donor.total)}</p>
            <p className="mt-1 text-sm text-ink-600">
              捐給 {formatNumber(donor.org_count)} 個組織，共 {formatNumber(donor.donation_count)} 筆
            </p>
          </Card>
        }
      >
        <p className="flex flex-wrap items-center gap-2 text-sm text-ink-600">
          <span className="rounded bg-ink-100 px-1.5 text-ink-700">{donor.kind_label}</span>
          {donor.ubn && <span className="font-num tabular-nums">統一編號 {donor.ubn}</span>}
        </p>
      </PageHeader>

      <Overview donor={donor} />

      {ov.active_years.length >= 2 && (
        <section>
          <h2 className="mb-3 font-display text-xl font-bold text-ink-900">近 5 年捐款趨勢</h2>
          <Card>
            <DonorTrendChart yearly={ov.yearly} partialYear={ov.yearly[ov.yearly.length - 1].year} />
            <p className="mt-3 text-xs text-ink-600">依捐款日期的年度加總；清冊上沒有日期的捐款不畫進圖，但算在總額裡。</p>
          </Card>
        </section>
      )}

      {donor.fields_breakdown.length > 0 && <FieldBreakdown rows={donor.fields_breakdown} />}

      {donor.esg && <EsgSection esg={donor.esg} />}

      {donor.ubn && (
        <section>
          <h2 className="mb-3 font-display text-xl font-bold text-ink-900">公司登記</h2>
          <Card>
            <dl className="divide-y divide-ink-100">
              <Row label="登記名稱">{donor.registered_name || "—"}</Row>
              <Row label="代表人">{donor.representative || "—"}</Row>
              <Row label="實收資本額">{donor.capital ? formatMoney(donor.capital) : "—"}</Row>
              <Row label="登記地址">{donor.address || "—"}</Row>
            </dl>
            <p className="mt-2 text-xs text-ink-600">來源：經濟部商工登記公示資料</p>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 font-display text-xl font-bold text-ink-900">捐給哪些組織</h2>
        <Card className="p-0 sm:p-0">
          <ol className="divide-y divide-ink-100">
            {donor.organizations.map((o, i) => (
              <li key={o.ubn} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                <span className="w-6 text-right font-semibold tabular-nums text-ink-500">{i + 1}</span>
                <span className="min-w-0 flex-1 break-words">
                  <TextLink href={`/orgs/${o.ubn}?tab=donations`}>{o.name}</TextLink>
                  <span className="ml-2 text-xs text-ink-500 tabular-nums">{formatNumber(o.count)} 筆</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1 text-xs">
                    {o.years.map((y) => (
                      <span key={y} className="rounded bg-brand-50 px-1.5 tabular-nums text-brand-800">
                        {y} 年
                      </span>
                    ))}
                    {o.penalty_count > 0 && (
                      <Link
                        href={`/orgs/${o.ubn}?tab=penalties`}
                        className="rounded bg-red-100 px-1.5 text-red-800 underline underline-offset-2 hover:bg-red-200"
                      >
                        裁罰 {formatNumber(o.penalty_count)} 筆
                      </Link>
                    )}
                  </span>
                </span>
                <span className="font-medium tabular-nums">{formatMoney(o.total)}</span>
              </li>
            ))}
          </ol>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 font-display text-xl font-bold text-ink-900">
          捐款明細{shown < donor.donation_count ? `（最近 ${formatNumber(shown)} 筆）` : ""}
        </h2>
        <Card className="overflow-x-auto p-0 sm:p-0">
          <table className="w-full text-sm">
            <thead className="bg-ink-50 text-ink-700">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium whitespace-nowrap">日期</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">組織／活動</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">金額</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">用途</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              {donor.donations.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="px-3 py-2 tabular-nums whitespace-nowrap">{formatDonationWhen(d)}</td>
                  <td className="px-3 py-2">
                    <TextLink href={`/orgs/${d.org_ubn}?tab=donations`}>{d.org_name}</TextLink>
                    {d.project_name && <span className="block text-xs text-ink-600">{d.project_name}</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{formatMoney(d.amount)}</td>
                  <td className="px-3 py-2 text-ink-700">
                    {d.purpose || "—"}
                    {d.source_url && (
                      <span className="block text-xs">
                        <TextLink href={d.source_url}>{shortSourceName(d.source_name) || "原始資料"}</TextLink>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  );
}

/** 依受捐組織的大類加總；組織屬於多個大類時各算全額，所以不畫成加起來 100% 的圓餅。 */
function FieldBreakdown({ rows }: { rows: DonorDetail["fields_breakdown"] }) {
  const max = Math.max(...rows.map((r) => r.total), 1);
  return (
    <section>
      <h2 className="mb-1 font-display text-xl font-bold text-ink-900">從捐款看關注議題</h2>
      <p className="mb-3 text-xs text-ink-600">受捐組織同時屬於多個領域時，金額會分別算進每個領域。</p>
      <Card>
        <ul className="space-y-2.5">
          {rows.map((r) => (
            <li key={r.code || "none"} className="grid grid-cols-[6rem_1fr_auto] items-center gap-3 text-sm">
              <span className="truncate">
                {r.code ? <TextLink href={`/categories/${r.code}`}>{r.label}</TextLink> : <span className="text-ink-600">{r.label}</span>}
              </span>
              <span className="h-2.5 overflow-hidden rounded-full bg-ink-100" aria-hidden>
                <span className="block h-full rounded-full bg-brand-600" style={{ width: `${(r.total / max) * 100}%` }} />
              </span>
              <span className="tabular-nums text-ink-900">{formatMoney(r.total)}</span>
            </li>
          ))}
        </ul>
      </Card>
    </section>
  );
}

/** 捐款概況四格（LK-38）：只放客觀數字，不打分數。 */
function Overview({ donor }: { donor: DonorDetail }) {
  const ov = donor.overview;
  const pct = Math.max(1, Math.ceil((ov.rank / Math.max(ov.rank_of, 1)) * 100));
  const stats: { label: string; value: string; note?: string }[] = [
    {
      label: `${donor.kind_label}排名`,
      value: `第 ${formatNumber(ov.rank)} 名`,
      // 「前 N%」不拆行（窄螢幕會斷成「前」與「1%」兩行）
      note: `共 ${formatNumber(ov.rank_of)} 個${donor.kind_label}・前 ${pct}%`,
    },
    {
      label: "持續支持",
      value: ov.active_years.length ? `${ov.active_years.length} 個年度` : "—",
      note: ov.active_years.length ? ov.active_years.join("、") : "清冊沒有捐款日期",
    },
    {
      label: "最近一次捐款",
      value: formatRocDate(ov.last_donated_on),
      note: ov.first_donated_on ? `第一次 ${formatRocDate(ov.first_donated_on)}` : undefined,
    },
    { label: "單筆最大", value: ov.max_donation >= 1e4 ? `${formatCompact(ov.max_donation)}元` : formatMoney(ov.max_donation) },
  ];
  return (
    <section aria-labelledby="donor-overview">
      <h2 id="donor-overview" className="mb-3 font-display text-xl font-bold text-ink-900">
        捐款概況
      </h2>
      <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="min-w-0">
            <dt className="text-sm text-ink-600">{s.label}</dt>
            <dd className="mt-1 font-num text-xl font-bold tabular-nums text-ink-900">{s.value}</dd>
            {s.note && <dd className="mt-0.5 break-words text-xs text-ink-600 tabular-nums">{s.note}</dd>}
          </Card>
        ))}
      </dl>
      <p className="mt-2 text-xs text-ink-600">
        以上依衛福部公益勸募活動的捐贈人清冊，與財團法人在官網公開的年度捐贈名單清冊計算，只涵蓋近 5 年；兩種清冊涵蓋的範圍不同，都不是這家{donor.kind_label}全部的捐款。
      </p>
    </section>
  );
}

const ESG_TEXTS: { key: keyof CompanyEsg; label: string }[] = [
  { key: "climate_targets", label: "氣候目標與進度" },
  { key: "transition_plan", label: "轉型計畫" },
  { key: "climate_actions", label: "因應極端氣候與轉型的行動" },
  { key: "climate_strategy", label: "氣候風險與機會對業務、策略的影響" },
  { key: "climate_governance", label: "董事會怎麼監督氣候議題" },
];
const EXCERPT = 120;

function formatTons(v: number): string {
  return `${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: v >= 100 ? 0 : 1 }).format(v)} 噸`;
}

function formatPct(v: number): string {
  return `${new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 2 }).format(v)}%`;
}

/** 上市櫃公司 ESG（LK-39）：公司自己申報的承諾與數字，照原文、不改寫；沒填的不顯示。 */
function EsgSection({ esg }: { esg: CompanyEsg }) {
  const texts = ESG_TEXTS.filter((t) => (esg[t.key] as string).trim());
  const verified = (s: string) => (s === "是" ? "已取得驗證" : s === "否" ? "未取得驗證" : s);
  const emissions =
    esg.scope1 != null || esg.scope2 != null
      ? {
          value: formatTons((esg.scope1 ?? 0) + (esg.scope2 ?? 0)),
          note: [
            esg.scope1 == null ? "只有範疇二" : esg.scope2 == null ? "只有範疇一" : "範疇一＋二",
            esg.scope1_verified && `範疇一${verified(esg.scope1_verified)}`,
          ]
            .filter(Boolean)
            .join("・"),
        }
      : null;
  const stats = [
    emissions && { label: "溫室氣體排放", value: emissions.value, note: emissions.note },
    esg.renewable_ratio != null && { label: "再生能源使用率", value: formatPct(esg.renewable_ratio) },
    esg.female_manager_ratio != null && { label: "女性主管占比", value: formatPct(esg.female_manager_ratio) },
    esg.salary_median != null && {
      label: "非主管員工薪資中位數",
      value: `${formatNumber(esg.salary_median)} 千元`,
      note: "全時員工、每人一年",
    },
  ].filter(Boolean) as { label: string; value: string; note?: string }[];
  if (!texts.length && !stats.length) return null;

  return (
    <section aria-labelledby="donor-esg">
      <h2 id="donor-esg" className="mb-1 font-display text-xl font-bold text-ink-900">
        永續承諾與揭露（ESG）
      </h2>
      <p className="mb-3 text-sm text-ink-600">
        {esg.short_name || esg.name}・{esg.market_label} {esg.code}・{esg.report_year} 年度申報
      </p>
      <div className="space-y-3">
        {stats.length > 0 && (
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {stats.map((s) => (
              <Card key={s.label} className="min-w-0">
                <dt className="text-sm text-ink-600">{s.label}</dt>
                <dd className="mt-1 font-num text-xl font-bold tabular-nums text-ink-900">{s.value}</dd>
                {s.note && <dd className="mt-0.5 break-words text-xs text-ink-600">{s.note}</dd>}
              </Card>
            ))}
          </dl>
        )}
        {texts.length > 0 && (
          <Card className="p-0 sm:p-0">
            <div className="divide-y divide-ink-100">
              {texts.map((t) => (
                <EsgText key={t.key} label={t.label} text={(esg[t.key] as string).trim()} />
              ))}
            </div>
          </Card>
        )}
      </div>
      <p className="mt-2 text-xs text-ink-600">
        以上為公司自行向主管機關申報的內容，本站未查證。
        <SourceNote name={esg.source_name} url={esg.source_url} />
        {esg.website && (
          <>
            {"　"}
            <TextLink href={esg.website} target="_blank" rel="noopener noreferrer">
              公司網站
            </TextLink>
          </>
        )}
      </p>
    </section>
  );
}

function EsgText({ label, text }: { label: string; text: string }) {
  const long = text.length > EXCERPT;
  return (
    <div className="px-4 py-3">
      <h3 className="text-sm font-semibold text-ink-900">{label}</h3>
      {long ? (
        <details className="group/esg mt-1 text-sm text-ink-800">
          <summary className="cursor-pointer list-none">
            <span className="whitespace-pre-line break-words group-open/esg:hidden">{text.slice(0, EXCERPT)}…</span>
            <span className="ml-1 text-brand-800 underline underline-offset-2 group-open/esg:hidden">看全文</span>
            <span className="hidden text-brand-800 underline underline-offset-2 group-open/esg:inline">收起</span>
          </summary>
          <p className="mt-1 whitespace-pre-line break-words">{text}</p>
        </details>
      ) : (
        <p className="mt-1 whitespace-pre-line break-words text-sm text-ink-800">{text}</p>
      )}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[8rem_1fr]">
      <dt className="text-sm text-ink-600">{label}</dt>
      <dd className="break-words text-ink-900">{children}</dd>
    </div>
  );
}

export function DonorDetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <Skeleton className="h-4 w-24" />
      <div className="flex flex-col gap-4 sm:flex-row sm:justify-between">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-28 w-full sm:w-72" />
      </div>
      <Skeleton className="h-48 w-full" />
    </div>
  );
}
