import Link from "next/link";
import type { ReactNode } from "react";

import { formatMoney, formatRocDate } from "@/lib/format";
import type { FieldPickOrg } from "@/lib/types";

import { LevelBadge, LevelProgress, levelName } from "./ui";

/**
 * 推薦卡（LK-52）：引導模式與領域區共用。每一行回答一件捐款人在意的事，點了到組織頁對應分頁。
 * 沒有資料的行照樣列、寫「尚無資料」，讓人知道我們有查。
 * 理念（LK-54）、新聞（LK-55）：後端送了那一欄才出現那一行。
 */
export function PickCard({ o, penaltySources }: { o: FieldPickOrg; penaltySources: string[] }) {
  const base = `/orgs/${o.ubn}`;
  return (
    <article className="flex h-full flex-col rounded-xl border border-ink-200 bg-white p-4 transition duration-200 hover:border-brand-300 hover:shadow-[var(--shadow-card-hover)]">
      <h3 className="min-w-0">
        <Link href={base} className="font-semibold text-brand-900 underline-offset-2 hover:underline">
          {o.name}
        </Link>
      </h3>
      {o.city && <p className="mt-0.5 text-xs text-ink-600">{o.city}</p>}
      <ul className="mt-3 divide-y divide-ink-100 border-t border-ink-100 text-sm">
        {o.mission !== undefined && (
          <Row label="理念" href={base}>
            {o.mission ? <span className="line-clamp-3">{o.mission}</span> : <NoData />}
          </Row>
        )}
        <Row label="捐款用途" href={purposeHref(o, base)}>
          <Purpose o={o} />
        </Row>
        <Row label="裁罰紀錄" href={`${base}?tab=penalties`}>
          <span className="text-ink-900">近五年無裁罰紀錄</span>
          {o.older_penalties > 0 && <span className="text-ink-700">，五年前有 {o.older_penalties} 筆</span>}
          {penaltySources.length > 0 && (
            <span className="mt-0.5 block text-xs text-ink-500">查過的來源：{penaltySources.join("、")}</span>
          )}
        </Row>
        <Row label="經費" href={`${base}?tab=donations`}>
          {o.raised_5y > 0 ? (
            <span className="tabular-nums text-ink-900">近 5 年實募 {formatMoney(o.raised_5y)}</span>
          ) : (
            <NoData />
          )}
        </Row>
        <Row label="揭露層級" href={base}>
          <span className="flex items-center gap-2">
            <LevelBadge level={o.level} />
            <span className="text-ink-700">{levelName(o.level)}</span>
          </span>
          <LevelProgress level={o.level} className="mt-2 max-w-40" />
        </Row>
        {o.news !== undefined && (
          <Row label="近期新聞" href={base}>
            {o.news?.length ? <span className="line-clamp-2">{o.news[0].title}</span> : <NoData />}
          </Row>
        )}
      </ul>
    </article>
  );
}

function purposeHref(o: FieldPickOrg, base: string) {
  const id = o.campaign?.project_id || o.latest_project?.project_id;
  return `${base}?tab=projects${id ? `#p-${id}` : ""}`;
}

function Purpose({ o }: { o: FieldPickOrg }) {
  if (o.campaign) {
    return (
      <>
        <span className="mr-1.5 rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand-800">募款中</span>
        <span className="text-ink-900">{o.campaign.name}</span>
        <span className="mt-0.5 block text-xs tabular-nums text-ink-600">
          預募 {formatMoney(o.campaign.target)}・至 {formatRocDate(o.campaign.end_date)}
        </span>
      </>
    );
  }
  if (o.latest_project) {
    return (
      <>
        <span className="text-ink-900">{o.latest_project.name}</span>
        <span className="mt-0.5 block text-xs text-ink-600">
          最近一次公益勸募{o.latest_project.year ? `（${o.latest_project.year} 年）` : ""}
        </span>
      </>
    );
  }
  return <NoData />;
}

function NoData() {
  return <span className="text-ink-500">尚無資料</span>;
}

/** 一行：左邊小標、右邊內容，整行是一個連結 */
function Row({ label, href, children }: { label: string; href: string; children: ReactNode }) {
  return (
    <li>
      <Link
        href={href}
        className="group grid grid-cols-[4.5rem_minmax(0,1fr)_0.75rem] items-start gap-2 py-2.5 transition-colors hover:bg-brand-50/50"
      >
        <span className="pt-px text-xs font-medium text-ink-600">{label}</span>
        <span className="min-w-0">{children}</span>
        <span aria-hidden className="pt-px text-ink-400 transition-transform group-hover:translate-x-0.5 group-hover:text-brand-700">
          ›
        </span>
      </Link>
    </li>
  );
}

/** 推薦卡一排：窄螢幕橫滑（露出下一張的邊，看得出可以滑），寬螢幕三欄。卡片行數多，平板寬度三欄太擠，到 lg 才排三欄 */
export const pickRow =
  "-mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-1 lg:mx-0 lg:grid lg:grid-cols-3 lg:overflow-visible lg:px-0 lg:pb-0";
export const pickItem = "w-[82%] max-w-80 shrink-0 snap-start lg:w-auto lg:max-w-none";
