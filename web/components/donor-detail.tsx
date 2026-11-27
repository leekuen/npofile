import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { formatMoney, formatNumber, formatRocDate } from "@/lib/format";
import { ApiUnavailableError, getDonor } from "@/lib/server-api";
import type { DonorDetail } from "@/lib/types";

import { Card, ErrorBox, Skeleton, TextLink } from "./ui";

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

  return (
    <div className="space-y-6">
      <nav className="text-sm">
        <TextLink href="/donors">‹ 捐款企業列表</TextLink>
      </nav>

      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold break-words text-slate-900 sm:text-3xl">{donor.name}</h1>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span className="rounded bg-slate-100 px-1.5 text-slate-700">{donor.kind_label}</span>
            {donor.ubn && <span className="tabular-nums">統一編號 {donor.ubn}</span>}
          </p>
        </div>
        <Card className="w-full shrink-0 sm:w-72">
          <p className="text-sm text-slate-600">近 5 年清冊上的捐款總額</p>
          <p className="mt-1 text-2xl font-bold tabular-nums text-slate-900">{formatMoney(donor.total)}</p>
          <p className="mt-1 text-sm text-slate-600">
            捐給 {formatNumber(donor.org_count)} 個組織，共 {formatNumber(donor.donation_count)} 筆
          </p>
        </Card>
      </header>

      {donor.ubn && (
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-900">公司登記</h2>
          <Card>
            <dl className="divide-y divide-slate-100">
              <Row label="登記名稱">{donor.registered_name || "—"}</Row>
              <Row label="代表人">{donor.representative || "—"}</Row>
              <Row label="實收資本額">{donor.capital ? formatMoney(donor.capital) : "—"}</Row>
              <Row label="登記地址">{donor.address || "—"}</Row>
            </dl>
            <p className="mt-2 text-xs text-slate-600">來源：經濟部商工登記公示資料</p>
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">捐給哪些組織</h2>
        <Card className="p-0 sm:p-0">
          <ol className="divide-y divide-slate-100">
            {donor.organizations.map((o, i) => (
              <li key={o.ubn} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
                <span className="w-6 text-right font-semibold tabular-nums text-slate-500">{i + 1}</span>
                <span className="min-w-0 flex-1 break-words">
                  <TextLink href={`/orgs/${o.ubn}?tab=donations`}>{o.name}</TextLink>
                  <span className="ml-2 text-xs text-slate-500 tabular-nums">{formatNumber(o.count)} 筆</span>
                </span>
                <span className="font-medium tabular-nums">{formatMoney(o.total)}</span>
              </li>
            ))}
          </ol>
        </Card>
      </section>

      <section>
        <h2 className="mb-3 text-lg font-semibold text-slate-900">
          捐款明細{shown < donor.donation_count ? `（最近 ${formatNumber(shown)} 筆）` : ""}
        </h2>
        <Card className="overflow-x-auto p-0 sm:p-0">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-700">
              <tr>
                <th scope="col" className="px-3 py-2 text-left font-medium whitespace-nowrap">日期</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">組織／活動</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">金額</th>
                <th scope="col" className="px-3 py-2 text-left font-medium">用途</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {donor.donations.map((d) => (
                <tr key={d.id} className="align-top">
                  <td className="px-3 py-2 tabular-nums whitespace-nowrap">{formatRocDate(d.donated_on)}</td>
                  <td className="px-3 py-2">
                    <TextLink href={`/orgs/${d.org_ubn}?tab=donations`}>{d.org_name}</TextLink>
                    {d.project_name && <span className="block text-xs text-slate-600">{d.project_name}</span>}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{formatMoney(d.amount)}</td>
                  <td className="px-3 py-2 text-slate-700">
                    {d.purpose || "—"}
                    {d.source_url && (
                      <span className="block text-xs">
                        <TextLink href={d.source_url}>{d.source_name || "原始資料"}</TextLink>
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

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[8rem_1fr]">
      <dt className="text-sm text-slate-600">{label}</dt>
      <dd className="break-words text-slate-900">{children}</dd>
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
