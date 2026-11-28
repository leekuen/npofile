import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { formatDonationWhen, formatMoney, formatNumber, formatRocDate, shortSourceName } from "@/lib/format";
import { ApiUnavailableError, getOrg } from "@/lib/server-api";
import { GRANT_AGENCIES } from "@/lib/sources";
import type {
  CourtRegistration,
  Grant,
  OrgDetail,
  Project,
  RegistryEntry,
} from "@/lib/types";

import { OrgCategoryTags } from "./categories";
import { Comments } from "./comments";
import { CountUp } from "./count-up";
import { FinancialChart, TrendChart } from "./financial-chart";
import { HashHighlight } from "./hash-highlight";
import {
  Card,
  EmptyState,
  ErrorBox,
  PageHeader,
  LevelBadge,
  LevelProgress,
  order,
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
    <div className="space-y-8">
      <PageHeader crumbs={[{ href: "/", label: "組織" }]} title={org.name}>
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-600">
          <StatusBadge status={org.status} label={org.status_label} />
          <span className="font-num tabular-nums">統一編號 {org.ubn}</span>
          {org.city && (
            <span className="whitespace-nowrap">
              <span aria-hidden className="mr-2 text-ink-300">·</span>
              {org.city}
            </span>
          )}
          {org.org_type && (
            <span className="whitespace-nowrap">
              <span aria-hidden className="mr-2 text-ink-300">·</span>
              {org.org_type}
            </span>
          )}
        </p>
        <div className="pt-1">
          <OrgCategoryTags categories={org.categories} />
        </div>
        {org.court_dissolution && (
          <div role="alert" className="mt-4 rounded-2xl border border-red-300 bg-red-50 px-4 py-3 text-red-900">
            <p className="font-semibold">
              <span aria-hidden>⚠ </span>
              已向法院辦理解散（{formatRocDate(org.court_dissolution.posted_on)}，{org.court_dissolution.court}
              {org.court_dissolution.case_type === "liquidation_end" ? "，清算已終結" : ""}）
            </p>
            {org.court_dissolution.source_url && (
              <p className="mt-1 text-sm">
                <TextLink href={org.court_dissolution.source_url}>看法院公告</TextLink>
              </p>
            )}
          </div>
        )}
      </PageHeader>

      {/* 桌機：左欄摘要＋分頁，右欄揭露層級＋基本資料；手機依序疊成摘要、右欄、分頁 */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:grid-rows-[auto_1fr] lg:items-start">
        <div className="lg:col-start-1">
          <OrgSummary org={org} />
        </div>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:col-start-2 lg:row-span-2 lg:row-start-1">
          <LevelPanel org={org} />
          <FinanceSummaryCard org={org} />
          <ContactCard org={org} />
          <CourtRegistrationsCard regs={org.court_registrations} />
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
          <div key={tab} className="animate-rise pt-5">
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
      value: penalized ? `近 5 年 ${org.penalty_count_5y} 次` : "近 5 年無紀錄",
      tone: penalized ? "bg-red-50 text-red-900 ring-1 ring-red-300" : "surface text-ink-900",
      icon: penalized ? "⚠" : "✓",
    },
    {
      tab: "donations",
      label: "近 5 年公開募款",
      value: raised > 0 ? <CountUp value={raised} format="money" /> : "沒有紀錄",
      tone: "surface text-ink-900",
      icon: null,
    },
    {
      tab: "projects",
      label: "捐款專案",
      value: org.projects.length
        ? `${formatNumber(org.projects.length)} 個`
        : "沒有紀錄",
      tone: "surface text-ink-900",
      icon: null,
    },
    {
      tab: "grants",
      label: "政府補助",
      value: org.grants.length ? (
        <CountUp value={org.grants.reduce((sum, g) => sum + g.amount, 0)} format="money" />
      ) : (
        "沒有紀錄"
      ),
      tone: "surface text-ink-900",
      icon: null,
    },
  ];
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map((it, i) => (
        <li key={it.tab} style={order(i)} className="stagger animate-rise">
          <Link
            href={
              it.tab === DEFAULT_TAB
                ? `/orgs/${org.ubn}`
                : `/orgs/${org.ubn}?tab=${it.tab}`
            }
            scroll={false}
            className={`flex h-full flex-col rounded-2xl px-3 py-2.5 transition duration-200 hover:-translate-y-0.5 hover:shadow-[var(--shadow-card-hover)] motion-reduce:hover:translate-y-0 sm:px-4 sm:py-3 ${it.tone}`}
          >
            <span className="text-xs text-ink-600">{it.label}</span>
            <span className="mt-1 flex items-center gap-x-1.5 font-num text-sm font-semibold whitespace-nowrap tabular-nums sm:text-base">
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

// 條件沒達到時，點過去看得到相關資料的分頁
const CHECK_TAB: Record<string, string> = {
  results_filed: "projects",
  financial_recent: "finance",
  financial_consecutive: "finance",
  report: "finance",
};

/** 揭露層級卡（LK-35）：四層依序達成；沒達到的寫還差哪一條 */
function LevelPanel({ org }: { org: OrgDetail }) {
  const lv = org.levels;
  const next = lv.layers.find((l) => l.level === lv.level + 1);
  const nextMissing = next ? next.checks.filter((c) => !c.met).map((c) => (c.hint ? `${c.label}（${c.hint}）` : c.label)) : [];
  // 手機版只留一句：下一層還差什麼
  const oneLine = !lv.active
    ? `${org.status_label}，不分層級`
    : next
      ? `升到「${next.medal}」還差：${nextMissing.join("、")}`
      : "已經是最高一級";

  return (
    <section aria-label="揭露層級" className="rounded-2xl bg-sun-50 p-4 ring-1 ring-sun-100 lg:space-y-4 lg:p-5">
      <div>
        <p className="font-display text-lg font-bold text-ink-900">揭露層級</p>
        <div className="mt-2">
          <LevelBadge level={lv.level} size="lg" />
        </div>
        {lv.active && <LevelProgress level={lv.level} />}
        <p className="mt-2 text-sm text-ink-800 lg:hidden">{oneLine}</p>
      </div>
      <ol className={`hidden space-y-3 text-sm ${lv.active ? "lg:block" : ""}`}>
        {lv.layers.map((layer) => {
          const reached = layer.level <= lv.level;
          return (
            <li key={layer.level}>
              <p className="flex items-baseline gap-1.5">
                <span
                  aria-hidden
                  className={`w-4 shrink-0 text-center font-bold ${reached ? "text-emerald-700" : "text-ink-400"}`}
                >
                  {reached ? "✓" : "○"}
                </span>
                <span className={reached ? "font-medium text-ink-900" : "font-medium text-ink-600"}>
                  {layer.medal}　{layer.name}
                </span>
                <span className="sr-only">{reached ? "已達到" : "未達到"}</span>
              </p>
              {/* 只列下一層還差什麼；更後面的層級只寫名稱，免得一長串 */}
              {layer.level === lv.level + 1 && (
                <ul className="mt-1 space-y-0.5 pl-6 text-xs text-ink-600">
                  {layer.checks
                    .filter((c) => !c.met)
                    .map((c) => (
                      <li key={c.key}>
                        還差：
                        {CHECK_TAB[c.key] ? (
                          <Link
                            href={`/orgs/${org.ubn}?tab=${CHECK_TAB[c.key]}`}
                            scroll={false}
                            className="text-brand-800 underline underline-offset-2"
                          >
                            {c.label}
                          </Link>
                        ) : (
                          c.label
                        )}
                        {c.hint && `（${c.hint}）`}
                      </li>
                    ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
      {!lv.active && <p className="hidden text-sm text-ink-800 lg:block">{org.status_label}的組織不分層級。</p>}
      <p className="hidden text-xs text-ink-500 lg:block">
        層級只代表公開了多少資料，不代表本站背書或評價；受裁罰紀錄不影響層級，另外標示。
      </p>
      {/* LK-42：給組織承辦人的入口（徽章與升級建議），桌機手機都看得到 */}
      <p className="mt-2 text-sm lg:mt-0">
        <TextLink href={`/orgs/${org.ubn}/kit`}>你是這個組織？取得徽章與升級建議</TextLink>
      </p>
    </section>
  );
}

/** 右欄財務摘要（LK-17，參照 Candid 組織頁的 Financials 卡）：最近一年三個數字＋連到財務分頁；沒有數字就不出 */
function FinanceSummaryCard({ org }: { org: OrgDetail }) {
  const latest = [...org.financials].sort((a, b) => b.year - a.year)[0];
  if (!latest) return null;
  // 顏色跟財務折線圖同一套（收入藍、支出橘、資產綠）
  const rows = [
    { label: "總收入", value: latest.total_revenue, color: "bg-[#4150b6]" },
    { label: "總支出", value: latest.total_expenses, color: "bg-[#c2610f]" },
    { label: "年底總資產", value: latest.total_assets, color: "bg-[#0f8a6c]" },
  ];
  const maxV = Math.max(0, ...rows.map((r) => r.value ?? 0));
  return (
    <section aria-labelledby="finance-summary-title" className="surface p-4 lg:p-5">
      <h2 id="finance-summary-title" className="font-display text-lg font-bold text-ink-900">
        財務摘要
      </h2>
      <p className="mt-0.5 text-xs text-ink-600">民國 {latest.year} 年度</p>
      <dl className="mt-3 space-y-3 text-sm">
        {rows.map((r, i) => (
          <div key={r.label}>
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-ink-700">{r.label}</dt>
              <dd className="font-num font-semibold tabular-nums text-ink-900">
                {r.value === null ? formatMoney(r.value) : <CountUp value={r.value} format="money" />}
              </dd>
            </div>
            {maxV > 0 && r.value !== null && r.value > 0 && (
              <div aria-hidden className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink-100">
                <div
                  style={{ width: `${(r.value / maxV) * 100}%`, animationDelay: `${0.2 + i * 0.12}s` }}
                  className={`animate-grow-x h-full origin-left rounded-full ${r.color}`}
                />
              </div>
            )}
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
  // 名冊與捐贈碼的出處接在財政部等來源後面（同名的只列一次）
  const sources = [
    ...org.source_links,
    ...[...org.registries, ...org.donation_codes].map((x) => ({
      name: x.source_name,
      url: x.source_url,
    })),
  ].filter(
    (src, i, all) => src.name && all.findIndex((s) => s.name === src.name) === i,
  );
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
      {org.donation_codes.length > 0 && (
        <Field label="發票捐贈碼">
          <span className="font-mono text-base font-bold tracking-wider">
            {org.donation_codes.map((c) => c.code).join("、")}
          </span>
          <span className="mt-0.5 block text-xs text-ink-600">
            結帳時說出或掃描這個碼，就能把發票捐給這個組織
          </span>
        </Field>
      )}
      <Field label={sameAddress ? "地址" : "聯絡地址"}>
        {org.contact_address || org.registered_address || NA}
      </Field>
      {!sameAddress && org.contact_address && org.registered_address && (
        <Field label="登記地址">{org.registered_address}</Field>
      )}
      <Field label="負責人">{org.representative || NA}</Field>
      <Field label="勸募用途">{org.purposes || NA}</Field>
      {org.registries.map((r) => (
        <RegistryFields key={r.source_name} entry={r} />
      ))}
      <Field label="資料來源">
        {sources.length ? (
          <ul className="space-y-1">
            {sources.map((src) => (
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

/** 主管機關名冊那幾行（LK-32）：每一行都是有資料才出現 */
function RegistryFields({ entry }: { entry: RegistryEntry }) {
  const year = entry.data_date
    ? Number(entry.data_date.slice(0, 4)) - 1911
    : null;
  return (
    <>
      {entry.authority && <Field label="主管機關">{entry.authority}</Field>}
      {entry.registered_assets !== null && (
        <Field label="登記財產總額">
          {formatMoney(entry.registered_assets)}
          <span className="ml-1 text-xs text-ink-500">
            （{entry.authority}名冊{year ? `，${year} 年` : ""}）
          </span>
        </Field>
      )}
      {entry.status && <Field label="名冊狀態">{entry.status}</Field>}
    </>
  );
}

/** 右側欄的基本資料：桌機直接攤開；手機收起來，免得把分頁擠到下面 */
function ContactCard({ org }: { org: OrgDetail }) {
  return (
    <>
      <section
        aria-labelledby="contact-title"
        className="hidden surface p-5 lg:block"
      >
        <h2
          id="contact-title"
          className="font-display text-lg font-bold text-ink-900"
        >
          基本資料
        </h2>
        <ContactFields org={org} />
      </section>
      <details className="group surface px-4 py-3 lg:hidden">
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

const COURT_RECENT = 5;

function CourtRegistrationItem({ r }: { r: CourtRegistration }) {
  const dissolved = r.case_type === "dissolution" || r.case_type === "liquidation_end";
  return (
    <li className="border-t border-ink-100 pt-2 first:border-t-0 first:pt-0">
      <p className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className={`font-medium ${dissolved ? "text-red-800" : "text-ink-900"}`}>{r.case_label}</span>
        <span className="text-xs tabular-nums text-ink-600">{formatRocDate(r.posted_on)}</span>
      </p>
      <p className="text-xs text-ink-600">{r.court}</p>
      {r.change_items.length > 0 && <p className="text-xs text-ink-700">變更：{r.change_items.join("、")}</p>}
      {r.property_total !== null && (
        <p className="text-xs text-ink-700">
          財產總額 <span className="font-num tabular-nums">{formatMoney(r.property_total)}</span>
        </p>
      )}
      {r.source_url && (
        <p className="text-xs">
          <TextLink href={r.source_url}>法院公告</TextLink>
        </p>
      )}
    </li>
  );
}

function CourtRegistrationsBody({ regs }: { regs: CourtRegistration[] }) {
  const recent = regs.slice(0, COURT_RECENT);
  const rest = regs.slice(COURT_RECENT);
  return (
    <>
      {regs.length === 0 ? (
        <p className="mt-2 text-sm text-ink-600">司法院法人登記公告（108 年 12 月起）查無這個組織的登記異動。</p>
      ) : (
        <>
          <ul className="mt-3 space-y-2 text-sm">
            {recent.map((r) => (
              <CourtRegistrationItem key={r.id} r={r} />
            ))}
          </ul>
          {rest.length > 0 && (
            <details className="group/more mt-2">
              <summary className="cursor-pointer list-none text-sm text-brand-800 underline underline-offset-2">
                <span className="group-open/more:hidden">看全部 {regs.length} 筆</span>
                <span className="hidden group-open/more:inline">收起</span>
              </summary>
              <ul className="mt-2 space-y-2 border-t border-ink-100 pt-2 text-sm">
                {rest.map((r) => (
                  <CourtRegistrationItem key={r.id} r={r} />
                ))}
              </ul>
            </details>
          )}
          <p className="mt-3 border-t border-ink-100 pt-3">
            <SourceNote name="司法院 法人登記公告" url="https://www.judicial.gov.tw/tw/lp-144-1.html" />
          </p>
        </>
      )}
    </>
  );
}

/** 基本資料下方：司法院法人登記公告（LK-31），最近 5 筆，其餘可展開；手機跟基本資料一樣收起來 */
function CourtRegistrationsCard({ regs }: { regs: CourtRegistration[] }) {
  return (
    <>
      <section aria-labelledby="court-title" className="hidden surface p-5 lg:block">
        <h2 id="court-title" className="font-display text-lg font-bold text-ink-900">
          法院登記異動
        </h2>
        <CourtRegistrationsBody regs={regs} />
      </section>
      <details className="group surface px-4 py-3 lg:hidden">
        <summary className="flex cursor-pointer list-none items-center justify-between font-display font-bold text-ink-900">
          法院登記異動
          <span aria-hidden className="text-ink-500 transition-transform group-open:rotate-90">
            ›
          </span>
        </summary>
        <div className="mt-3">
          <CourtRegistrationsBody regs={regs} />
        </div>
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

// 顏色跟著種類走（勸募藍、集資橘、補助綠），某種沒有資料時其他線不換色
const DONATION_SERIES = [
  { key: "permit", label: "公益勸募", styleIndex: 0 },
  { key: "crowdfunding", label: "群眾集資", styleIndex: 1 },
  { key: "grants", label: "政府補助", styleIndex: 2 },
] as const;

/** 近 5 年受捐款趨勢（LK-33）：至少 2 個年度有金額才畫；只畫有錢的線 */
function DonationTrend({ org }: { org: OrgDetail }) {
  const rows = org.donation_trend ?? [];
  const funded = rows.filter((r) => r.permit > 0 || r.crowdfunding > 0 || r.grants > 0);
  if (funded.length < 2) return null;
  const series = DONATION_SERIES.filter((s) => rows.some((r) => r[s.key] > 0)).map((s) => ({ ...s }));
  return (
    <section>
      <SectionTitle>近 5 年受捐款趨勢</SectionTitle>
      <Card>
        <TrendChart
          rows={rows}
          series={series}
          label={`近 ${rows.length} 年${series.map((s) => s.label).join("、")}金額折線圖，數字見下方表格與政府補助分頁`}
          partialYear={org.since_roc_year + 4}
        />
        <p className="mt-3 text-xs text-ink-600">
          三種錢來源不同、可能重疊，所以分開畫、不相加；沒有收錄到的年度畫成 0。
        </p>
      </Card>
    </section>
  );
}

function DonationsTab({ org }: { org: OrgDetail }) {
  const years = fundedYears(org);
  const maxRaised = Math.max(0, ...years.map((a) => a.raised));
  const pr = org.public_raised;
  return (
    <div className="space-y-6">
      <DonationTrend org={org} />
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
                {years.map((a, i) => (
                  <tr key={`${a.year}-${a.source_name}`} className="transition-colors hover:bg-brand-50/40">
                    <td className="px-2 py-2 sm:px-3">{a.year}</td>
                    <td
                      className="hidden px-2 py-2 sm:px-3 sm:table-cell"
                      aria-hidden
                    >
                      <div
                        className="animate-grow-x h-3 origin-left rounded-r-md bg-gradient-to-r from-brand-400 to-brand-700"
                        style={{
                          width: `${maxRaised ? (a.raised / maxRaised) * 100 : 0}%`,
                          animationDelay: `${0.1 + i * 0.08}s`,
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
                      {a.achievement_rate === null ? "—" : <AchievementRate rate={a.achievement_rate} />}
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
                      {formatDonationWhen(d)}
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
                          {shortSourceName(d.source_name) || "原始資料"}
                        </TextLink>
                      ) : (
                        shortSourceName(d.source_name) || "—"
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
          這個組織還沒有公開勸募活動的捐贈人清冊或年度捐贈名單清冊，或還沒有抓取。
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
                    {d.sources.length > 0 && (
                      <span className="block text-xs text-ink-600">
                        {d.sources.map(shortSourceName).join("、")}
                      </span>
                    )}
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
  const lists = org.annual_donor_lists ?? [];
  const docYears = [...new Set([...org.documents, ...lists].map((d) => d.year))].sort((a, b) => b - a);
  const hasDocs = org.documents.length > 0 || lists.length > 0;

  if (years.length === 0 && !hasDocs) {
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
                        {f.method === "ocr" && <span className="mt-0.5 inline-block rounded bg-sun-100 px-1.5 text-xs text-ink-700">影像辨識</span>}
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
            <p className="text-xs text-ink-600">金額單位：元。業務支出占比＝業務（服務）支出 ÷ 總支出。報告沒有列的項目顯示「—」。
              {years.some((f) => f.method === "ocr") && "標「影像辨識」的年度是從掃描檔讀出的數字，可能有誤，請以原始報告為準。"}
            </p>
          </div>
        )}
      </section>

      {hasDocs && (
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
                    {lists
                      .filter((d) => d.year === y)
                      .map((d) => (
                        <li key={d.url} className="flex flex-wrap items-baseline gap-x-2 break-words">
                          <span className="rounded bg-ink-100 px-1.5 text-xs text-ink-700">
                            {d.direction_label}捐贈名單
                          </span>
                          <TextLink href={d.url}>{d.title}</TextLink>
                          {d.scanned && (
                            <span className="rounded bg-sun-100 px-1.5 text-xs text-ink-700">掃描檔，尚未讀取</span>
                          )}
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
                  <FilingStatus filedOn={p.result_filed_on} done={p.result_done} late={p.result_late} dueOn={p.result_due_on} />
                </div>
                <div>
                  <dt className="text-ink-600">結案備查</dt>
                  <FilingStatus filedOn={p.closed_filed_on} done={p.closed_done} late={p.closed_late} dueOn={p.closed_due_on} />
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

const PENALTY_CATEGORY = {
  labor: "勞動法令",
  fundraising: "公益勸募",
  environment: "環境保護",
  procurement: "政府採購停權",
} as const;

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
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="inline-flex items-center rounded-full bg-ink-100 px-2 py-0.5 text-xs font-medium text-ink-800 ring-1 ring-inset ring-ink-500/30">
                {PENALTY_CATEGORY[p.category]}
              </span>
              <span className="text-sm font-semibold tabular-nums text-red-900">
                處分日期 {formatRocDate(p.decided_on)}
              </span>
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

/** 成果／結案備查一格（LK-43）：有日期寫日期；活動頁看得到已備查寫「已備查」；還沒備查寫期限，過了期限標紅字「逾期未備查」。
 * 逾期才補交的加註「逾期」。期限是公益勸募條例的法定期限（成果＝期滿後 30 日，結案＝財物用完後 30 日）。 */
function FilingStatus({ filedOn, done, late, dueOn }: { filedOn: string | null; done: boolean | null; late: boolean; dueOn: string | null }) {
  const lateNote = late ? <span className="ml-1 text-xs text-ink-600">（逾期）</span> : null;
  if (filedOn || done) {
    return (
      <dd className="tabular-nums">
        {filedOn ? formatRocDate(filedOn) : "已備查"}
        {lateNote}
      </dd>
    );
  }
  if (dueOn) {
    const overdue = new Date(dueOn) < new Date(new Date().toDateString());
    return (
      <dd className="tabular-nums">
        {overdue ? (
          <span className="font-medium text-red-700">逾期未備查</span>
        ) : (
          <>還沒到期</>
        )}
        <span className="block text-xs text-ink-600">期限 {formatRocDate(dueOn)}</span>
      </dd>
    );
  }
  return <dd className="tabular-nums">尚未備查</dd>;
}


/** 達成率：數字＋一條小進度條（滿 100% 換綠色，超過的部分不畫出框） */
function AchievementRate({ rate }: { rate: number }) {
  const full = rate >= 100;
  return (
    <span className="inline-flex items-center justify-end gap-2">
      <span aria-hidden className="hidden h-1.5 w-12 overflow-hidden rounded-full bg-ink-100 sm:block">
        <span
          style={{ width: `${Math.min(100, rate)}%` }}
          className={`animate-grow-x block h-full origin-left rounded-full ${full ? "bg-emerald-600" : "bg-brand-500"}`}
        />
      </span>
      <span className={full ? "font-semibold text-emerald-800" : ""}>{rate}%</span>
    </span>
  );
}
