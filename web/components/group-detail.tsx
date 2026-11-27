import { notFound } from "next/navigation";

import { formatMoney, formatNumber } from "@/lib/format";
import { ApiUnavailableError, getDonorGroup } from "@/lib/server-api";
import type { DonorGroupDetail } from "@/lib/types";

import { FieldBreakdown } from "./donor-detail";
import { Card, ErrorBox, TextLink } from "./ui";

/** 集團頁（LK-23）：旗下捐款公司、合計、捐給哪些領域與組織。 */
export async function GroupDetailView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let group: DonorGroupDetail | null;
  try {
    group = await getDonorGroup(id);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前讀不到這個集團的資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  if (!group) notFound();

  return (
    <div className="space-y-6">
      <nav className="text-sm">
        <TextLink href="/donors?view=group">‹ 集團排行</TextLink>
      </nav>

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-extrabold break-words text-ink-900 sm:text-3xl">{group.label}</h1>
          <p className="mt-2 max-w-prose text-sm text-ink-600">
            這 {formatNumber(group.member_count)} 家公司的董監事由{group.name}或彼此出任（經濟部商工登記）。
            只表示有這層關係，不代表持股比例或誰控制誰。
          </p>
        </div>
        <Card className="w-full shrink-0 sm:w-72">
          <p className="text-sm text-ink-600">近 5 年清冊上的捐款合計</p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-ink-900">{formatMoney(group.total)}</p>
          <p className="mt-1 text-sm text-ink-600">
            捐給 {formatNumber(group.org_count)} 個組織，共 {formatNumber(group.donation_count)} 筆
          </p>
        </Card>
      </header>

      <section>
        <h2 className="mb-3 font-display text-xl font-bold text-ink-900">旗下捐款公司</h2>
        <Card className="p-0 sm:p-0">
          <ol className="divide-y divide-ink-100">
            {group.members.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                <span className="min-w-0 flex-1 break-words">
                  <TextLink href={`/donors/${m.id}`}>{m.name}</TextLink>
                  <span className="ml-2 text-xs text-ink-500 tabular-nums">捐給 {formatNumber(m.org_count)} 個組織</span>
                </span>
                <span className="font-medium tabular-nums">{formatMoney(m.total)}</span>
              </li>
            ))}
          </ol>
        </Card>
      </section>

      {group.fields_breakdown.length > 0 && <FieldBreakdown rows={group.fields_breakdown} />}

      <section>
        <h2 className="mb-3 font-display text-xl font-bold text-ink-900">捐給哪些組織</h2>
        <Card className="p-0 sm:p-0">
          <ol className="divide-y divide-ink-100">
            {group.organizations.map((o, i) => (
              <li key={o.ubn} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                <span className="w-6 text-right font-semibold tabular-nums text-ink-500">{i + 1}</span>
                <span className="min-w-0 flex-1 break-words">
                  <TextLink href={`/orgs/${o.ubn}?tab=donations`}>{o.name}</TextLink>
                  <span className="ml-2 text-xs text-ink-500 tabular-nums">{formatNumber(o.count)} 筆</span>
                </span>
                <span className="font-medium tabular-nums">{formatMoney(o.total)}</span>
              </li>
            ))}
          </ol>
        </Card>
      </section>
    </div>
  );
}
