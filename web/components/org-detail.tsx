import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { formatMoney, formatNumber, formatRocDate } from "@/lib/format";
import { ApiUnavailableError, getOrg } from "@/lib/server-api";
import { GRANT_AGENCIES } from "@/lib/sources";
import type { Grant, OrgDetail, Project, ScoreBreakdown } from "@/lib/types";

import { OrgCategoryTags } from "./categories";
import { Comments } from "./comments";
import { FinancialChart } from "./financial-chart";
import { HashHighlight } from "./hash-highlight";
import {
  Card,
  EmptyState,
  ErrorBox,
  ScoreBadge,
  Skeleton,
  SourceNote,
  StatusBadge,
  TextLink,
} from "./ui";

// 基本資料改放右側欄（LK-11），分頁只留資料；舊連結 ?tab=basic 會落到預設分頁
const TABS = [
  { key: "donations", label: "募款與捐款人" },
  { key: "finance", label: "財務與年報" },
  { key: "projects", label: "捐款專案" },
  { key: "grants", label: "政府補助" },
  { key: "penalties", label: "受裁罰紀錄" },
] as const;
type TabKey = (typeof TABS)[number]["key"];
const DEFAULT_TAB: TabKey = "donations";

export async function OrgDetailView({
  params,
  searchParams,
}: {
  params: Promise<{ ubn: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ ubn }, sp] = await Promise.all([params, searchParams]);
  const rawTab = Array.isArray(sp.tab) ? sp.tab[0] : sp.tab;
  const tab: TabKey = TABS.some((t) => t.key === rawTab)
    ? (rawTab as TabKey)
    : DEFAULT_TAB;

  let org: OrgDetail | null;
  try {
    org = await getOrg(ubn);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return (
        <ErrorBox title="目前讀不到這個組織的資料">
          資料服務暫時沒有回應，請稍後重新整理。
        </ErrorBox>
      );
    }
    throw e;
  }
  if (!org) notFound();

  // 只有裁罰需要一眼看到筆數；其他分頁的數字不會改變點不點進去
  const counts: Record<TabKey, number | null> = {
    donations: null,
    finance: null,
    projects: null,
    grants: null,
    penalties: org.penalties.length || null,
  };

  return (
    <div className="space-y-6">
      <nav className="text-sm">
        <TextLink href="/">‹ 組織列表</TextLink>
      </nav>

      <header>
        <h1 className="font-display text-2xl font-extrabold text-balance break-words text-ink-900 sm:text-3xl">
          {org.name}
        </h1>
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-600">
          <span className="tabular-nums">統一編號 {org.ubn}</span>
          {org.city && <span>{org.city}</span>}
          {org.org_type && <span>{org.org_type}</span>}
          <StatusBadge status={org.status} label={org.status_label} />
        </p>
        <div className="mt-3">
          <OrgCategoryTags categories={org.categories} />
        </div>
      </header>

      {/* 桌機：左欄摘要＋分頁，右欄揭露指數＋基本資料；手機依序疊成摘要、右欄、分頁 */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div className="lg:col-start-1">
          <OrgSummary org={org} />
        </div>

        <aside className="space-y-4 lg:sticky lg:top-6 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <ScorePanel score={org.score} />
          <FinanceSummaryCard org={org} />
          <ContactCard org={org} />
        </aside>

        <div className="min-w-0 lg:col-start-1">
          <nav
            aria-label="資料分類"
            className="-mx-4 overflow-x-auto px-4 lg:mx-0 lg:px-0"
          >
            <ul className="flex min-w-max gap-1 border-b border-ink-200">
              {TABS.map((t) => {
                const active = t.key === tab;
                return (
                  <li key={t.key}>
                    <Link
                      href={
                        t.key === DEFAULT_TAB
                          ? `/orgs/${org.ubn}`
                          : `/orgs/${org.ubn}?tab=${t.key}`
                      }
                      scroll={false}
                      aria-current={active ? "page" : undefined}
                      className={`-mb-px inline-flex items-center gap-1 border-b-2 px-3 py-3 text-sm font-medium ${
                        active
                          ? "border-brand-700 font-bold text-brand-900"
                          : "border-transparent text-ink-600 hover:text-ink-900"
                      }`}
                    >
                      {t.label}
                      {counts[t.key] !== null && (
                        <span className="rounded-full bg-red-100 px-1.5 text-xs tabular-nums text-red-800">
                          {counts[t.key]}
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className="pt-5">
            <p className="mb-4 text-sm text-ink-600">
              {tab === "penalties"
                ? "所有年度"
                : `近 5 年（民國 ${org.since_roc_year} 年起）`}
            </p>
            {tab === "donations" && <DonationsTab org={org} />}
            {tab === "finance" && <FinanceTab org={org} />}
            {tab === "projects" && <ProjectsTab org={org} />}
            {tab === "grants" && <GrantsTab grants={org.grants} />}
            {tab === "penalties" && <PenaltiesTab org={org} />}
          </div>
        </div>
      </div>

      <Comments ubn={org.ubn} />
    </div>
  );
}

/** 頁首摘要：裁罰、近 5 年公開募款、專案數、政府補助，點了跳到對應分頁 */
function OrgSummary({ org }: { org: OrgDetail }) {
  const raised = org.public_raised.total;
  const penalized = org.penalty_count_5y > 0;
  const items = [
    {
      tab: "penalties",
      label: "受裁罰",
      value: penalized ? `近五年 ${org.penalty_count_5y} 次` : "近五年無紀錄",
      tone: penalized
        ? "border-red-300 bg-red-50 text-red-900"
        : "border-ink-200 bg-white text-ink-900",
      icon: penalized ? "⚠" : "✓",
    },
    {
      tab: "donations",
      label: "近 5 年公開募款",
      value: raised > 0 ? formatMoney(raised) : "沒有紀錄",
      tone: "border-ink-200 bg-white text-ink-900",
      icon: null,
    },
    {
      tab: "projects",
      label: "捐款專案",
      value: org.projects.length
        ? `${formatNumber(org.projects.length)} 個`
        : "沒有紀錄",
      tone: "border-ink-200 bg-white text-ink-900",
      icon: null,
    },
    {
      tab: "grants",
      label: "政府補助",
      value: org.grants.length
        ? formatMoney(org.grants.reduce((sum, g) => sum + g.amount, 0))
        : "沒有紀錄",
      tone: "border-ink-200 bg-white text-ink-900",
      icon: null,
    },
  ];
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map((it) => (
        <li key={it.tab}>
          <Link
            href={
              it.tab === DEFAULT_TAB
                ? `/orgs/${org.ubn}`
                : `/orgs/${org.ubn}?tab=${it.tab}`
            }
            scroll={false}
            className={`flex h-full flex-col rounded-2xl border px-2.5 py-2 hover:border-brand-600 sm:px-3 sm:py-2.5 ${it.tone}`}
          >
            <span className="text-xs text-ink-600">{it.label}</span>
            <span className="mt-0.5 flex items-center gap-x-1.5 font-num text-[0.8125rem] font-semibold whitespace-nowrap tabular-nums sm:text-base">
              {it.icon && (
                <span aria-hidden className="hidden sm:inline">
                  {it.icon}
                </span>
              )}
              {it.value}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function ScorePanel({ score }: { score: ScoreBreakdown }) {
  const missing = (
    [
      ["org_type", "團體類型"],
      ["address", "地址"],
      ["phone", "電話"],
      ["website", "官網"],
      ["purposes", "勸募用途"],
    ] as const
  )
    .filter(([k]) => !score.basic_present[k])
    .map(([, label]) => label);

  const rows: { label: string; got: number; max: number; note: string }[] = [
    {
      label: "基本資料",
      got: score.basic,
      max: score.basic_max,
      note: missing.length ? `缺：${missing.join("、")}` : "齊全",
    },
    {
      label: "近五年募款紀錄",
      got: score.fundraising,
      max: score.fundraising_max,
      note: score.fundraising ? "有" : "沒有",
    },
    {
      label: "捐款專案",
      got: score.project,
      max: score.project_max,
      note: score.project ? "有" : "沒有",
    },
    {
      label: "專案成果備查",
      got: score.result,
      max: score.result_max,
      note: score.result_funded_projects
        ? `${score.result_filed_projects} / ${score.result_funded_projects} 個有募到款的專案已備查`
        : "沒有募到款的專案",
    },
  ];

  const full = rows.filter((r) => r.max > 0 && r.got >= r.max);
  const partial = rows.filter((r) => !(r.max > 0 && r.got >= r.max));
  // 手機版只留一句：扣在哪
  const oneLine = partial.length
    ? `${partial.map((r) => `${r.label} ${r.got}/${r.max}`).join("、")}${full.length ? "，其餘滿分" : ""}`
    : "每一項都拿到滿分";

  return (
    <section
      aria-label="揭露指數"
      className="rounded-2xl bg-sun-50 p-4 ring-1 ring-sun-100 lg:space-y-4 lg:p-5"
    >
      <div className="flex items-center gap-4">
        <ScoreBadge score={score.total} size="lg" />
        <div>
          <p className="font-display text-lg font-bold text-ink-900">
            揭露指數
          </p>
          <p className="text-xs text-ink-600">資料公開得越完整，分數越高</p>
          <p className="mt-1 text-sm text-ink-800 lg:hidden">{oneLine}</p>
        </div>
      </div>
      <div className="hidden space-y-3 text-sm lg:block">
        {partial.length > 0 && (
          <ul className="space-y-3">
            {partial.map((r) => (
              <li key={r.label}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium text-ink-800">{r.label}</span>
                  <span className="font-num tabular-nums text-ink-900">
                    {r.got} / {r.max}
                  </span>
                </div>
                <div
                  className="mt-1 h-1.5 overflow-hidden rounded-full bg-white"
                  aria-hidden
                >
                  <div
                    className="h-full rounded-full bg-brand-600"
                    style={{ width: `${r.max ? (r.got / r.max) * 100 : 0}%` }}
                  />
                </div>
                <p className="mt-0.5 text-xs text-ink-600">{r.note}</p>
              </li>
            ))}
          </ul>
        )}
        {full.length > 0 && (
          <p className="text-ink-700">
            <span aria-hidden className="mr-1 font-bold text-emerald-700">
              ✓
            </span>
            {full.map((r) => r.label).join("、")}拿到滿分
          </p>
        )}
        <p className="text-xs text-ink-500">
          受裁罰紀錄不影響揭露指數，另外標示。
        </p>
      </div>
    </section>
  );
}

/** 右欄財務摘要（LK-17，參照 Candid 組織頁的 Financials 卡）：最近一年三個數字＋連到財務分頁；沒有數字就不出 */
function FinanceSummaryCard({ org }: { org: OrgDetail }) {
  const latest = [...org.financials].sort((a, b) => b.year - a.year)[0];
  if (!latest) return null;
  const rows = [
    { label: "總收入", value: latest.total_revenue },
    { label: "總支出", value: latest.total_expenses },
    { label: "年底總資產", value: latest.total_assets },
  ];
  return (
    <section aria-labelledby="finance-summary-title" className="rounded-2xl border border-ink-200 bg-white p-4 lg:p-5">
      <h2 id="finance-summary-title" className="font-display text-lg font-bold text-ink-900">
        財務摘要
      </h2>
      <p className="mt-0.5 text-xs text-ink-600">民國 {latest.year} 年度</p>
      <dl className="mt-3 space-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-ink-700">{r.label}</dt>
            <dd className="font-num font-semibold tabular-nums text-ink-900">{formatMoney(r.value)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 border-t border-ink-100 pt-3 text-sm">
        <TextLink href={`/orgs/${org.ubn}?tab=finance`} scroll={false}>
          看更多財務資料
        </TextLink>
      </p>
    </section>
  );
}

const NA = <span className="text-ink-500">未收錄</span>;

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="mt-0.5 break-words text-ink-900">{children}</dd>
    </div>
  );
}

/** 右側欄的基本資料：聯絡方式放前面，捐款前最常用 */
function ContactFields({ org }: { org: OrgDetail }) {
  const sameAddress =
    org.contact_address && org.contact_address === org.registered_address;
  return (
    <dl className="mt-3 space-y-3 text-sm">
      <Field label="電話">
        {org.phone ? (
          <a
            href={`tel:${org.phone}`}
            className="text-brand-800 underline underline-offset-2"
          >
            {org.phone}
          </a>
        ) : (
          NA
        )}
      </Field>
      <Field label="官網">
        {org.website ? (
          <TextLink href={org.website}>
            {org.website.replace(/^https?:\/\//, "").replace(/\/$/, "")}
          </TextLink>
        ) : (
          NA
        )}
      </Field>
      <Field label={sameAddress ? "地址" : "聯絡地址"}>
        {org.contact_address || org.registered_address || NA}
      </Field>
      {!sameAddress && org.contact_address && org.registered_address && (
        <Field label="登記地址">{org.registered_address}</Field>
      )}
      <Field label="負責人">{org.representative || NA}</Field>
      <Field label="勸募用途">{org.purposes || NA}</Field>
      <Field label="資料來源">
        {org.source_links.length ? (
          <ul className="space-y-1">
            {org.source_links.map((src) => (
              <li key={src.name}>
                <TextLink href={src.url}>{src.name}</TextLink>
              </li>
            ))}
          </ul>
        ) : (
          "管理員手動建立"
        )}
      </Field>
    </dl>
  );
}

/** 右側欄的基本資料：桌機直接攤開；手機收起來，免得把分頁擠到下面 */
function ContactCard({ org }: { org: OrgDetail }) {
  return (
    <>
      <section
        aria-labelledby="contact-title"
        className="hidden rounded-2xl border border-ink-200 bg-white p-5 lg:block"
      >
        <h2
          id="contact-title"
          className="font-display text-lg font-bold text-ink-900"
        >
          基本資料
        </h2>
        <ContactFields org={org} />
      </section>
      <details className="group rounded-2xl border border-ink-200 bg-white px-4 py-3 lg:hidden">
        <summary className="flex cursor-pointer list-none items-center justify-between font-display font-bold text-ink-900">
          基本資料與聯絡方式
          <span
            aria-hidden
            className="text-ink-500 transition-transform group-open:rotate-90"
          >
            ›
          </span>
        </summary>
        <ContactFields org={org} />
      </details>
    </>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-3 font-display text-xl font-bold text-ink-900">
      {children}
    </h2>
  );
}

/** 來源會列出沒有勸募的年度（含未來年度），實募與預募都是 0 的不顯示 */
function fundedYears(org: OrgDetail) {
  return org.annual_records.filter((a) => a.raised > 0 || a.target > 0);
}

function DonationsTab({ org }: { org: OrgDetail }) {
  const years = fundedYears(org);
  const maxRaised = Math.max(0, ...years.map((a) => a.raised));
  const pr = org.public_raised;
  return (
    <div className="space-y-6">
      {pr.crowdfunding > 0 && (
        <section>
          <SectionTitle>近 5 年公開募款</SectionTitle>
          <Card>
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-ink-600">合計</dt>
                <dd className="font-num text-lg font-semibold tabular-nums">{formatMoney(pr.total)}</dd>
              </div>
              <div>
                <dt className="text-ink-600">公益勸募申報</dt>
                <dd className="font-num font-semibold tabular-nums">{formatMoney(pr.permit)}</dd>
              </div>
              <div>
                <dt className="text-ink-600">群眾集資</dt>
                <dd className="font-num font-semibold tabular-nums">
                  {formatMoney(pr.crowdfunding)}
                  {pr.crowdfunding_counted < pr.crowdfunding && (
                    <span className="ml-1 text-xs font-normal text-ink-600">計入 {formatMoney(pr.crowdfunding_counted)}</span>
                  )}
                </dd>
              </div>
            </dl>
            {pr.crowdfunding_counted < pr.crowdfunding && (
              <p className="mt-3 text-xs text-ink-600">當年度已申報勸募的，不再加計同年度的群眾集資，避免同一筆捐款算兩次。</p>
            )}
          </Card>
        </section>
      )}
      <section>
        <SectionTitle>年度募款</SectionTitle>
        {years.length === 0 ? (
          <EmptyState title="近 5 年沒有收錄到募款紀錄">
            這個組織可能近年沒有向主管機關申請公益勸募。
          </EmptyState>
        ) : (
          <Card className="overflow-x-auto p-0 sm:p-0">
            <table className="w-full text-sm">
              <thead className="bg-ink-50 text-ink-700">
                <tr>
                  <th
                    scope="col"
                    className="px-2 py-2 sm:px-3 text-left font-medium whitespace-nowrap"
                  >
                    年度（民國）
                  </th>
                  <th
                    scope="col"
                    className="hidden w-full min-w-16 px-2 py-2 sm:px-3 text-left font-medium sm:table-cell"
                  >
                    <span className="sr-only">實募金額比較</span>
                  </th>
                  <th
                    scope="col"
                    className="px-2 py-2 sm:px-3 text-right font-medium whitespace-nowrap"
                  >
                    實募金額
                  </th>
                  <th
                    scope="col"
                    className="px-2 py-2 sm:px-3 text-right font-medium whitespace-nowrap"
                  >
                    預募金額
                  </th>
                  <th
                    scope="col"
                    className="px-2 py-2 sm:px-3 text-right font-medium whitespace-nowrap"
                  >
                    達成率
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 tabular-nums">
                {years.map((a) => (
                  <tr key={`${a.year}-${a.source_name}`}>
                    <td className="px-2 py-2 sm:px-3">{a.year}</td>
                    <td
                      className="hidden px-2 py-2 sm:px-3 sm:table-cell"
                      aria-hidden
                    >
                      <div
                        className="h-3 rounded-sm bg-brand-600"
                        style={{
                          width: `${maxRaised ? (a.raised / maxRaised) * 100 : 0}%`,
                        }}
                      />
                    </td>
                    <td className="px-2 py-2 sm:px-3 text-right whitespace-nowrap">
                      {formatMoney(a.raised)}
                    </td>
                    <td className="px-2 py-2 sm:px-3 text-right whitespace-nowrap">
                      {formatMoney(a.target)}
                    </td>
                    <td className="px-2 py-2 sm:px-3 text-right">
                      {a.achievement_rate === null
                        ? "—"
                        : `${a.achievement_rate}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="border-t border-ink-100 px-3 py-2">
              <SourceNote
                name={years[0].source_name}
                url={years[0].source_url}
              />
            </p>
          </Card>
        )}
      </section>

      <DonorRankings org={org} />

      {org.donations.length > 0 && (
        <section>
          <SectionTitle>
            捐款明細（最近 {org.donations.length} 筆）
          </SectionTitle>
          <Card className="overflow-x-auto p-0 sm:p-0">
            <table className="w-full text-sm">
              <thead className="bg-ink-50 text-ink-700">
                <tr>
                  <th
                    scope="col"
                    className="px-3 py-2 text-left font-medium whitespace-nowrap"
                  >
                    日期
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    捐款人
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    金額
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    用途
                  </th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">
                    來源
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {org.donations.map((d) => (
                  <tr key={d.id}>
                    <td className="px-3 py-2 tabular-nums whitespace-nowrap">
                      {formatRocDate(d.donated_on)}
                    </td>
                    <td className="px-3 py-2">
                      {d.donor_id ? (
                        <TextLink href={`/donors/${d.donor_id}`}>
                          {d.donor_name}
                        </TextLink>
                      ) : (
                        d.donor_name
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">
                      {formatMoney(d.amount)}
                    </td>
                    <td className="px-3 py-2 text-ink-700">
                      {d.purpose || "—"}
                    </td>
                    <td className="px-3 py-2">
                      {d.source_url ? (
                        <TextLink href={d.source_url}>
                          {d.source_name || "原始資料"}
                        </TextLink>
                      ) : (
                        d.source_name || "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>
      )}
    </div>
  );
}

function DonorRankings({ org }: { org: OrgDetail }) {
  const summary = org.donor_summary;
  if (
    !org.corporate_donors.length &&
    !org.individual_donors.length &&
    !summary
  ) {
    return (
      <section>
        <SectionTitle>捐款人</SectionTitle>
        <EmptyState title="目前沒有收錄到具名的捐款人">
          這個組織的勸募活動還沒有公開捐贈人清冊，或還沒有抓取。
        </EmptyState>
      </section>
    );
  }
  return (
    <>
      <section>
        <SectionTitle>企業與團體捐款人</SectionTitle>
        {org.corporate_donors.length === 0 ? (
          <EmptyState title="清冊上沒有企業或團體捐款人" />
        ) : (
          <Card className="p-0 sm:p-0">
            <ol className="divide-y divide-ink-100">
              {org.corporate_donors.map((d, i) => (
                <li
                  key={d.donor_id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm"
                >
                  <span className="w-6 text-right font-semibold tabular-nums text-ink-500">
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 break-words">
                    <TextLink href={`/donors/${d.donor_id}`}>{d.name}</TextLink>
                    <span className="ml-2 inline-block rounded bg-ink-100 px-1.5 text-xs text-ink-700">
                      {d.kind_label}
                    </span>
                  </span>
                  <span className="tabular-nums font-medium">
                    {formatMoney(d.total)}
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </section>

      <section>
        <SectionTitle>大額個人捐款人</SectionTitle>
        {summary && (
          <p className="-mt-2 mb-3 text-xs text-ink-600">
            個人只列出在同一個勸募活動累計捐款 {formatMoney(summary.threshold)}
            以上者。
          </p>
        )}
        {org.individual_donors.length === 0 ? (
          <EmptyState title="沒有達到門檻的個人捐款人" />
        ) : (
          <Card className="p-0 sm:p-0">
            <ol className="divide-y divide-ink-100">
              {org.individual_donors.map((d, i) => (
                <li
                  key={d.name}
                  className="flex items-center gap-3 px-4 py-2.5 text-sm"
                >
                  <span className="w-6 text-right font-semibold tabular-nums text-ink-500">
                    {i + 1}
                  </span>
                  <span className="flex-1 break-words">{d.name}</span>
                  <span className="tabular-nums font-medium">
                    {formatMoney(d.total)}
                  </span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </section>

      {summary && (
        <section>
          <SectionTitle>捐贈人清冊摘要</SectionTitle>
          <Card>
            <dl className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-ink-600">
                  清冊合計（{formatNumber(summary.lists)} 份）
                </dt>
                <dd className="font-semibold tabular-nums">
                  {formatNumber(summary.total_rows)} 筆，
                  {formatMoney(summary.total_amount)}
                </dd>
              </div>
              <div>
                <dt className="text-ink-600">其他個人捐款</dt>
                <dd className="font-semibold tabular-nums">
                  {formatNumber(summary.small_individual_count)} 人次，
                  {formatMoney(summary.small_individual_amount)}
                </dd>
              </div>
              <div>
                <dt className="text-ink-600">匿名或不公開</dt>
                <dd className="font-semibold tabular-nums">
                  {formatNumber(summary.anonymous_rows)} 筆，
                  {formatMoney(summary.anonymous_amount)}
                </dd>
              </div>
            </dl>
          </Card>
        </section>
      )}
    </>
  );
}

const FIN_COLUMNS = [
  { key: "total_revenue", label: "總收入" },
  { key: "contributions", label: "捐款收入" },
  { key: "government_grants", label: "政府補助" },
  { key: "total_expenses", label: "總支出" },
  { key: "program_expense_ratio", label: "業務支出占比" },
  { key: "net_assets", label: "年底淨資產" },
] as const;

/** 財務與年報（LK-17）：組織官網公開的報告，數字經管理員審核後才上架 */
function FinanceTab({ org }: { org: OrgDetail }) {
  const years = [...org.financials].sort((a, b) => b.year - a.year);
  const docYears = [...new Set(org.documents.map((d) => d.year))].sort((a, b) => b - a);

  if (years.length === 0 && org.documents.length === 0) {
    return (
      <EmptyState title="還沒有收錄到這個組織官網公開的財務報告">
        {org.website ? "我們會定期到組織官網找年報與財務報告。" : "這個組織沒有登記官網，目前無法自動收錄。"}
      </EmptyState>
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <SectionTitle>收入、支出與淨資產</SectionTitle>
        {years.length === 0 ? (
          <EmptyState title="報告裡的數字還沒整理上架">下方可以先看組織公開的原始報告。</EmptyState>
        ) : (
          <div className="space-y-3">
            {years.length >= 2 && (
              <Card>
                <FinancialChart
                  rows={years.map((f) => ({ year: f.year, revenue: f.total_revenue, expenses: f.total_expenses, netAssets: f.net_assets }))}
                />
              </Card>
            )}
            <Card className="overflow-x-auto p-0! sm:p-0!">
              <table className="w-full text-sm">
                <thead className="bg-ink-50 text-ink-700">
                  <tr>
                    <th scope="col" className="sticky left-0 bg-ink-50 px-2.5 py-2 text-left font-medium whitespace-nowrap">年度</th>
                    {FIN_COLUMNS.map((c) => (
                      <th key={c.key} scope="col" className="px-2.5 py-2 text-right font-medium whitespace-nowrap">{c.label}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100 tabular-nums">
                  {years.map((f) => (
                    <tr key={f.year}>
                      <td className="sticky left-0 bg-white px-2.5 py-2 whitespace-nowrap">
                        {f.year}
                        {f.document_url && (
                          <span className="block text-xs">
                            <TextLink href={f.document_url}>原始報告</TextLink>
                          </span>
                        )}
                      </td>
                      {FIN_COLUMNS.map((c) => {
                        const v = f[c.key];
                        return (
                          <td key={c.key} className="px-2.5 py-2 text-right align-top whitespace-nowrap">
                            {v === null ? "—" : c.key === "program_expense_ratio" ? `${v}%` : formatNumber(v)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            <p className="text-xs text-ink-600">金額單位：元。業務支出占比＝業務（服務）支出 ÷ 總支出。報告沒有列的項目顯示「—」。</p>
          </div>
        )}
      </section>

      {org.documents.length > 0 && (
        <section>
          <SectionTitle>官網公開的報告</SectionTitle>
          <Card className="p-0 sm:p-0">
            <ul className="divide-y divide-ink-100">
              {docYears.map((y) => (
                <li key={y} className="flex flex-col gap-1 px-4 py-3 text-sm sm:flex-row sm:gap-4">
                  <span className="w-16 shrink-0 font-semibold tabular-nums text-ink-700">{y} 年</span>
                  <ul className="min-w-0 flex-1 space-y-1">
                    {org.documents
                      .filter((d) => d.year === y)
                      .map((d) => (
                        <li key={d.id} className="flex flex-wrap items-baseline gap-x-2 break-words">
                          <span className="rounded bg-ink-100 px-1.5 text-xs text-ink-700">{d.kind_label}</span>
                          <TextLink href={d.url}>{d.title}</TextLink>
                        </li>
                      ))}
                  </ul>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      )}
    </div>
  );
}

function ProjectsTab({ org }: { org: OrgDetail }) {
  if (org.projects.length === 0) {
    return (
      <EmptyState title="近 5 年沒有收錄到捐款專案">
        這個組織可能近年沒有經許可的勸募活動，或專案資料尚未整理上架。
      </EmptyState>
    );
  }
  return (
    <ul className="space-y-3">
      <HashHighlight />
      {org.projects.map((p) => (
        <li
          key={p.id}
          id={p.external_id ? `p-${p.external_id}` : undefined}
          className="scroll-mt-24 rounded-2xl data-highlight:ring-2 data-highlight:ring-brand-600 data-highlight:ring-offset-2"
        >
          {p.channel === "crowdfunding" ? (
            <CrowdfundingCard p={p} />
          ) : (
            <Card>
              <h3 className="font-semibold break-words text-ink-900">
                {p.name}
              </h3>
              {p.category && (
                <p className="mt-1 text-xs text-ink-600">{p.category}</p>
              )}
              <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-ink-600">預募金額</dt>
                  <dd className="tabular-nums">{formatMoney(p.target)}</dd>
                </div>
                <div>
                  <dt className="text-ink-600">實募金額</dt>
                  <dd className="tabular-nums">{formatMoney(p.raised)}</dd>
                </div>
                <div>
                  <dt className="text-ink-600">成果備查</dt>
                  <dd className="tabular-nums">
                    {p.result_filed_on
                      ? formatRocDate(p.result_filed_on)
                      : "尚未備查"}
                  </dd>
                </div>
                <div>
                  <dt className="text-ink-600">結案備查</dt>
                  <dd className="tabular-nums">
                    {p.closed_filed_on
                      ? formatRocDate(p.closed_filed_on)
                      : "尚未結案"}
                  </dd>
                </div>
                {(p.start_date || p.end_date) && (
                  <div className="col-span-2">
                    <dt className="text-ink-600">活動期間</dt>
                    <dd className="tabular-nums">
                      {formatRocDate(p.start_date)} ～{" "}
                      {formatRocDate(p.end_date)}
                    </dd>
                  </div>
                )}
                {p.region && (
                  <div className="col-span-2">
                    <dt className="text-ink-600">活動地區</dt>
                    <dd>{p.region}</dd>
                  </div>
                )}
                {p.permit_no && (
                  <div className="col-span-2">
                    <dt className="text-ink-600">許可文號</dt>
                    <dd className="break-words">{p.permit_no}</dd>
                  </div>
                )}
              </dl>
              {p.description && (
                <p className="mt-3 text-sm whitespace-pre-line text-ink-800">
                  {p.description}
                </p>
              )}
              <p className="mt-3">
                <SourceNote name={p.source_name} url={p.source_url} />
              </p>
            </Card>
          )}
        </li>
      ))}
    </ul>
  );
}

/** 群眾集資專案（LK-15）：沒有許可文號與備查，金額是平台的即時數字；定期定額是每月的，不跟一次性的相加。 */
function CrowdfundingCard({ p }: { p: Project }) {
  const monthly = p.monthly_raised != null;
  return (
    <Card>
      <p className="text-xs font-medium text-brand-700">群眾集資・挖貝</p>
      <h3 className="mt-1 font-semibold break-words text-ink-900">{p.name}</h3>
      {p.category && <p className="mt-1 text-xs text-ink-600">{p.category}</p>}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        {p.target != null && (
          <div>
            <dt className="text-ink-600">目標金額</dt>
            <dd className="tabular-nums">{formatMoney(p.target)}</dd>
          </div>
        )}
        <div>
          <dt className="text-ink-600">{monthly ? "單次贊助" : "已募集"}</dt>
          <dd className="tabular-nums">{formatMoney(p.raised)}</dd>
        </div>
        {monthly && (
          <div>
            <dt className="text-ink-600">定期定額</dt>
            <dd className="tabular-nums">
              {formatMoney(p.monthly_raised)} / 月
            </dd>
          </div>
        )}
        <div>
          <dt className="text-ink-600">參與人次</dt>
          <dd className="tabular-nums">
            {p.backers != null ? formatNumber(p.backers) : "—"}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-ink-600">集資期間</dt>
          <dd className="tabular-nums">
            {formatRocDate(p.start_date)} ～{" "}
            {p.end_date ? formatRocDate(p.end_date) : "長期集資"}
          </dd>
        </div>
      </dl>
      <p className="mt-3 text-xs text-ink-600">
        金額為挖貝頁面顯示的即時數字；當年度的公益勸募還沒申報時，會計入近 5 年公開募款。
      </p>
      <p className="mt-2">
        <SourceNote name={p.source_name} url={p.source_url} />
      </p>
    </Card>
  );
}

/** 政府補助（LK-19）：依年度分組，組內金額大的在前；附設單位的補助標出是哪個單位。 */
function GrantsTab({ grants }: { grants: Grant[] }) {
  if (grants.length === 0) {
    return (
      <EmptyState title="近 5 年沒有收錄到政府補助">
        目前收錄{GRANT_AGENCIES}公開的補助名單；名單上的名稱要跟組織登記名稱相同才對得到。
      </EmptyState>
    );
  }
  const years = [...new Set(grants.map((g) => g.year))].sort((a, b) => b - a);
  const total = (ys: Grant[]) => ys.reduce((sum, g) => sum + g.amount, 0);
  return (
    <div className="space-y-6">
      {years.map((year) => {
        const rows = grants.filter((g) => g.year === year);
        const quarter = Math.max(...rows.map((g) => g.quarter));
        return (
          <section key={year} aria-labelledby={`grants-${year}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-ink-200 pb-2">
              <h3 id={`grants-${year}`} className="font-semibold text-ink-900">
                民國 {year} 年
                {quarter < 4 && (
                  <span className="ml-1 text-sm font-normal text-ink-600">
                    （截至第 {quarter} 季）
                  </span>
                )}
              </h3>
              <p className="font-num text-sm font-semibold tabular-nums text-ink-900">
                {formatNumber(rows.length)} 筆・{formatMoney(total(rows))}
              </p>
            </div>
            <ul className="divide-y divide-ink-100">
              {rows.map((g) => (
                <li
                  key={g.id}
                  className="flex items-start justify-between gap-4 py-3"
                >
                  <div className="min-w-0">
                    <p className="break-words text-ink-900">{g.purpose}</p>
                    <p className="mt-1 text-xs text-ink-600">
                      {g.agency}
                      {g.approved_on && (
                        <>・核准 {formatRocDate(g.approved_on)}</>
                      )}
                      {g.facility && <>・附設單位：{g.facility}</>}
                    </p>
                  </div>
                  <p className="shrink-0 font-num text-sm font-semibold tabular-nums text-ink-900">
                    {formatMoney(g.amount)}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
      <ul className="space-y-1">
        {[
          ...new Map(
            grants.map((g) => [g.source_name, g.source_url]),
          ).entries(),
        ].map(([name, url]) => (
          <li key={name}>
            <SourceNote name={name} url={url} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function PenaltiesTab({ org }: { org: OrgDetail }) {
  if (org.penalties.length === 0) {
    return (
      <EmptyState title="目前沒有收錄到受裁罰紀錄">
        已查過的來源沒有這個組織的裁罰公告；收錄範圍以頁尾列出的資料來源為準。
      </EmptyState>
    );
  }
  return (
    <ul className="space-y-3">
      {org.penalties.map((p) => (
        <li key={p.id}>
          <Card className="border-l-4 border-l-red-600">
            <p className="text-sm font-semibold tabular-nums text-red-900">
              處分日期 {formatRocDate(p.decided_on)}
            </p>
            <p className="mt-2 break-words text-ink-900">{p.content}</p>
            {p.fine_text && (
              <p className="mt-2 text-sm font-medium text-ink-800">
                {p.fine_text}
              </p>
            )}
            {(p.authority || p.document_no) && (
              <p className="mt-2 text-xs break-words text-ink-600">
                {p.authority && <>處分機關：{p.authority}</>}
                {p.authority && p.document_no && "　"}
                {p.document_no && <>文號：{p.document_no}</>}
              </p>
            )}
            {p.reason && (
              <details className="mt-2 text-sm">
                <summary className="cursor-pointer text-brand-800 underline underline-offset-2">
                  處分理由
                </summary>
                <p className="mt-1 whitespace-pre-line text-ink-800">
                  {p.reason}
                </p>
              </details>
            )}
            <p className="mt-3">
              <SourceNote name={p.source_name} url={p.source_url} />
            </p>
          </Card>
        </li>
      ))}
    </ul>
  );
}

export function OrgDetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy>
      <Skeleton className="h-4 w-24" />
      <div className="space-y-4">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
