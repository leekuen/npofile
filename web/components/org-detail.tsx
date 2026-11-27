import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { formatMoney, formatNumber, formatRocDate } from "@/lib/format";
import { ApiUnavailableError, getOrg } from "@/lib/server-api";
import type { OrgDetail, ScoreBreakdown } from "@/lib/types";

import { Comments } from "./comments";
import { Card, EmptyState, ErrorBox, PenaltyBadge, ScoreBadge, Skeleton, SourceNote, StatusBadge, TextLink } from "./ui";

const TABS = [
  { key: "basic", label: "基本資料" },
  { key: "donations", label: "過往受捐款資訊" },
  { key: "projects", label: "捐款專案" },
  { key: "penalties", label: "受裁罰紀錄" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export async function OrgDetailView({
  params,
  searchParams,
}: {
  params: Promise<{ ubn: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ ubn }, sp] = await Promise.all([params, searchParams]);
  const rawTab = Array.isArray(sp.tab) ? sp.tab[0] : sp.tab;
  const tab: TabKey = TABS.some((t) => t.key === rawTab) ? (rawTab as TabKey) : "basic";

  let org: OrgDetail | null;
  try {
    org = await getOrg(ubn);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前讀不到這個組織的資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  if (!org) notFound();

  // 只有裁罰需要一眼看到筆數；其他分頁的數字不會改變點不點進去
  const counts: Record<TabKey, number | null> = {
    basic: null,
    donations: null,
    projects: null,
    penalties: org.penalties.length || null,
  };

  return (
    <div className="space-y-6">
      <nav className="text-sm">
        <TextLink href="/">‹ 組織列表</TextLink>
      </nav>

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold break-words text-slate-900 sm:text-3xl">{org.name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span className="tabular-nums">統一編號 {org.ubn}</span>
            {org.org_type && <span>{org.org_type}</span>}
            <StatusBadge status={org.status} label={org.status_label} />
            <PenaltyBadge count={org.penalty_count_5y} />
          </p>
        </div>
        <ScorePanel score={org.score} />
      </header>

      <div>
        <nav aria-label="資料分類" className="-mx-4 overflow-x-auto px-4">
          <ul className="flex min-w-max gap-1 border-b border-slate-200">
            {TABS.map((t) => {
              const active = t.key === tab;
              return (
                <li key={t.key}>
                  <Link
                    href={t.key === "basic" ? `/orgs/${org.ubn}` : `/orgs/${org.ubn}?tab=${t.key}`}
                    scroll={false}
                    aria-current={active ? "page" : undefined}
                    className={`-mb-px inline-flex items-center gap-1 border-b-2 px-3 py-3 text-sm font-medium ${
                      active ? "border-teal-700 text-teal-900" : "border-transparent text-slate-600 hover:text-slate-900"
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
          {tab === "basic" && <BasicTab org={org} />}
          {tab === "donations" && <DonationsTab org={org} />}
          {tab === "projects" && <ProjectsTab org={org} />}
          {tab === "penalties" && <PenaltiesTab org={org} />}
        </div>
      </div>

      <Comments ubn={org.ubn} />
    </div>
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
    { label: "基本資料", got: score.basic, max: score.basic_max, note: missing.length ? `缺：${missing.join("、")}` : "齊全" },
    { label: "近五年募款紀錄", got: score.fundraising, max: score.fundraising_max, note: score.fundraising ? "有" : "沒有" },
    { label: "捐款專案", got: score.project, max: score.project_max, note: score.project ? "有" : "沒有" },
    {
      label: "專案成果備查",
      got: score.result,
      max: score.result_max,
      note: score.result_funded_projects
        ? `${score.result_filed_projects} / ${score.result_funded_projects} 個有募到款的專案已備查`
        : "沒有募到款的專案",
    },
  ];

  return (
    <Card className="w-full shrink-0 sm:w-80">
      <div className="flex items-center gap-4">
        <ScoreBadge score={score.total} size="lg" />
        <div>
          <p className="font-semibold text-slate-900">揭露指數</p>
          <p className="text-xs text-slate-600">資料公開得越完整分數越高</p>
        </div>
      </div>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-teal-800 underline underline-offset-2">怎麼算</summary>
        <table className="mt-2 w-full">
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-t border-slate-100 align-top">
                <th scope="row" className="py-1.5 pr-2 text-left font-medium text-slate-700">
                  {r.label}
                  <span className="block text-xs font-normal text-slate-500">{r.note}</span>
                </th>
                <td className="py-1.5 text-right tabular-nums text-slate-900">
                  {r.got} / {r.max}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-slate-500">受裁罰紀錄不影響揭露指數，另外標示。</p>
      </details>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-[8rem_1fr]">
      <dt className="text-sm text-slate-600">{label}</dt>
      <dd className="break-words text-slate-900">{children}</dd>
    </div>
  );
}

const NA = <span className="text-slate-500">未收錄</span>;

function BasicTab({ org }: { org: OrgDetail }) {
  return (
    <Card>
      <dl className="divide-y divide-slate-100">
        <Field label="負責人">{org.representative || NA}</Field>
        <Field label="團體類型">{org.org_type || NA}</Field>
        <Field label="所在縣市">{org.city || NA}</Field>
        <Field label="登記地址">{org.registered_address || NA}</Field>
        <Field label="聯絡地址">{org.contact_address || NA}</Field>
        <Field label="電話">{org.phone ? <a href={`tel:${org.phone}`} className="text-teal-800 underline underline-offset-2">{org.phone}</a> : NA}</Field>
        <Field label="官網">{org.website ? <TextLink href={org.website}>{org.website}</TextLink> : NA}</Field>
        <Field label="勸募用途">{org.purposes || NA}</Field>
        <Field label="資料來源">
          {org.source_links.length ? (
            <ul className="space-y-1">
              {org.source_links.map((s) => (
                <li key={s.name}>
                  <TextLink href={s.url}>{s.name}</TextLink>
                </li>
              ))}
            </ul>
          ) : (
            "管理員手動建立"
          )}
        </Field>
      </dl>
    </Card>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-lg font-semibold text-slate-900">{children}</h2>;
}

/** 來源會列出沒有勸募的年度（含未來年度），實募與預募都是 0 的不顯示 */
function fundedYears(org: OrgDetail) {
  return org.annual_records.filter((a) => a.raised > 0 || a.target > 0);
}

function DonationsTab({ org }: { org: OrgDetail }) {
  const years = fundedYears(org);
  return (
    <div className="space-y-6">
      <section>
        <SectionTitle>歷年募款</SectionTitle>
        {years.length === 0 ? (
          <EmptyState title="目前沒有收錄到歷年募款紀錄">這個組織可能沒有向主管機關申請公益勸募。</EmptyState>
        ) : (
          <Card className="overflow-x-auto p-0 sm:p-0">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-700">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">年度（民國）</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">實募金額</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">預募金額</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">勸募達成率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 tabular-nums">
                {years.map((a) => (
                  <tr key={`${a.year}-${a.source_name}`}>
                    <td className="px-3 py-2">{a.year}</td>
                    <td className="px-3 py-2 text-right">{formatMoney(a.raised)}</td>
                    <td className="px-3 py-2 text-right">{formatMoney(a.target)}</td>
                    <td className="px-3 py-2 text-right">{a.achievement_rate === null ? "—" : `${a.achievement_rate}%`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="border-t border-slate-100 px-3 py-2">
              <SourceNote name={years[0].source_name} url={years[0].source_url} />
            </p>
          </Card>
        )}
      </section>

      <DonorRankings org={org} />

      {org.donations.length > 0 && (
        <section>
          <SectionTitle>捐款明細（最近 {org.donations.length} 筆）</SectionTitle>
          <Card className="overflow-x-auto p-0 sm:p-0">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-slate-700">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium whitespace-nowrap">日期</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">捐款人</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">金額</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">用途</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">來源</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {org.donations.map((d) => (
                  <tr key={d.id}>
                    <td className="px-3 py-2 tabular-nums whitespace-nowrap">{formatRocDate(d.donated_on)}</td>
                    <td className="px-3 py-2">
                      {d.donor_id ? <TextLink href={`/donors/${d.donor_id}`}>{d.donor_name}</TextLink> : d.donor_name}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{formatMoney(d.amount)}</td>
                    <td className="px-3 py-2 text-slate-700">{d.purpose || "—"}</td>
                    <td className="px-3 py-2">{d.source_url ? <TextLink href={d.source_url}>{d.source_name || "原始資料"}</TextLink> : d.source_name || "—"}</td>
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
  if (!org.corporate_donors.length && !org.individual_donors.length && !summary) {
    return (
      <section>
        <SectionTitle>捐款人</SectionTitle>
        <EmptyState title="目前沒有收錄到具名的捐款人">這個組織的勸募活動還沒有公開捐贈人清冊，或還沒有抓取。</EmptyState>
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
            <ol className="divide-y divide-slate-100">
              {org.corporate_donors.map((d, i) => (
                <li key={d.donor_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                  <span className="w-6 text-right font-semibold tabular-nums text-slate-500">{i + 1}</span>
                  <span className="min-w-0 flex-1 break-words">
                    <TextLink href={`/donors/${d.donor_id}`}>{d.name}</TextLink>
                    <span className="ml-2 inline-block rounded bg-slate-100 px-1.5 text-xs text-slate-700">{d.kind_label}</span>
                  </span>
                  <span className="tabular-nums font-medium">{formatMoney(d.total)}</span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </section>

      <section>
        <SectionTitle>大額個人捐款人</SectionTitle>
        {summary && (
          <p className="-mt-2 mb-3 text-xs text-slate-600">
            個人只列出在同一個勸募活動累計捐款 {formatMoney(summary.threshold)}以上者。
          </p>
        )}
        {org.individual_donors.length === 0 ? (
          <EmptyState title="沒有達到門檻的個人捐款人" />
        ) : (
          <Card className="p-0 sm:p-0">
            <ol className="divide-y divide-slate-100">
              {org.individual_donors.map((d, i) => (
                <li key={d.name} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                  <span className="w-6 text-right font-semibold tabular-nums text-slate-500">{i + 1}</span>
                  <span className="flex-1 break-words">{d.name}</span>
                  <span className="tabular-nums font-medium">{formatMoney(d.total)}</span>
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
                <dt className="text-slate-600">清冊合計（{formatNumber(summary.lists)} 份）</dt>
                <dd className="font-semibold tabular-nums">
                  {formatNumber(summary.total_rows)} 筆，{formatMoney(summary.total_amount)}
                </dd>
              </div>
              <div>
                <dt className="text-slate-600">其他個人捐款</dt>
                <dd className="font-semibold tabular-nums">
                  {formatNumber(summary.small_individual_count)} 人次，{formatMoney(summary.small_individual_amount)}
                </dd>
              </div>
              <div>
                <dt className="text-slate-600">匿名或不公開</dt>
                <dd className="font-semibold tabular-nums">
                  {formatNumber(summary.anonymous_rows)} 筆，{formatMoney(summary.anonymous_amount)}
                </dd>
              </div>
            </dl>
          </Card>
        </section>
      )}
    </>
  );
}

function ProjectsTab({ org }: { org: OrgDetail }) {
  if (org.projects.length === 0) {
    return <EmptyState title="目前沒有收錄到捐款專案">這個組織可能沒有經許可的勸募活動，或專案資料尚未整理上架。</EmptyState>;
  }
  return (
    <ul className="space-y-3">
      {org.projects.map((p) => (
        <li key={p.id}>
          <Card>
            <h3 className="font-semibold break-words text-slate-900">{p.name}</h3>
            {p.category && <p className="mt-1 text-xs text-slate-600">{p.category}</p>}
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
              <div>
                <dt className="text-slate-600">預募金額</dt>
                <dd className="tabular-nums">{formatMoney(p.target)}</dd>
              </div>
              <div>
                <dt className="text-slate-600">實募金額</dt>
                <dd className="tabular-nums">{formatMoney(p.raised)}</dd>
              </div>
              <div>
                <dt className="text-slate-600">成果備查</dt>
                <dd className="tabular-nums">{p.result_filed_on ? formatRocDate(p.result_filed_on) : "尚未備查"}</dd>
              </div>
              <div>
                <dt className="text-slate-600">結案備查</dt>
                <dd className="tabular-nums">{p.closed_filed_on ? formatRocDate(p.closed_filed_on) : "尚未結案"}</dd>
              </div>
              {(p.start_date || p.end_date) && (
                <div className="col-span-2">
                  <dt className="text-slate-600">活動期間</dt>
                  <dd className="tabular-nums">
                    {formatRocDate(p.start_date)} ～ {formatRocDate(p.end_date)}
                  </dd>
                </div>
              )}
              {p.region && (
                <div className="col-span-2">
                  <dt className="text-slate-600">活動地區</dt>
                  <dd>{p.region}</dd>
                </div>
              )}
              {p.permit_no && (
                <div className="col-span-2">
                  <dt className="text-slate-600">許可文號</dt>
                  <dd className="break-words">{p.permit_no}</dd>
                </div>
              )}
            </dl>
            {p.description && <p className="mt-3 text-sm whitespace-pre-line text-slate-800">{p.description}</p>}
            <p className="mt-3">
              <SourceNote name={p.source_name} url={p.source_url} />
            </p>
          </Card>
        </li>
      ))}
    </ul>
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
            <p className="text-sm font-semibold tabular-nums text-red-900">處分日期 {formatRocDate(p.decided_on)}</p>
            <p className="mt-2 break-words text-slate-900">{p.content}</p>
            {p.fine_text && <p className="mt-2 text-sm font-medium text-slate-800">{p.fine_text}</p>}
            {p.authority && <p className="mt-2 text-xs text-slate-600">處分機關：{p.authority}</p>}
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
      <div className="flex flex-col gap-4 sm:flex-row sm:justify-between">
        <div className="flex-1 space-y-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
        <Skeleton className="h-32 w-full sm:w-80" />
      </div>
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}
