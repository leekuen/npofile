import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { OrgRows, OrgSearchSkeleton } from "@/components/org-search";
import { formatNumber } from "@/lib/format";
import { ApiUnavailableError, listOrgs } from "@/lib/server-api";
import { EmptyState, ErrorBox, PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "鑽石級組織" };

const PAGE_SIZE = 20;

/** 鑽石級（揭露層級 4）組織專頁（LK-46）：公開資訊最完整、從公開來源就查得到長期紀錄的組織 */
export default function DiamondPage({ searchParams }: PageProps<"/diamond">) {
  return (
    <div className="space-y-8">
      <PageHeader
        crumbs={[{ href: "/", label: "組織" }, { label: "鑽石級組織" }]}
        title="鑽石級組織"
        description={
          <>
            連續 3 個年度公開財務報告，近兩年也公開年報或工作、成果報告的組織。
            <Link href="/about#score" className="ml-1 text-brand-800 underline underline-offset-2 hover:text-brand-900">
              揭露層級怎麼算
            </Link>
          </>
        }
      />
      <Suspense fallback={<OrgSearchSkeleton />}>
        <DiamondList searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function DiamondList({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const raw = Array.isArray(sp.page) ? sp.page[0] : sp.page;
  const current = Math.max(1, Number(raw) || 1);
  let page;
  try {
    page = await listOrgs({ level: "4", page: String(current) });
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前查不到組織資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  const lastPage = Math.max(1, Math.ceil(page.count / PAGE_SIZE));
  const pageHref = (n: number) => (n === 1 ? "/diamond" : `/diamond?page=${n}`);

  if (page.count === 0) {
    return <EmptyState title="目前還沒有組織達到鑽石級">資料每天更新，組織公開更多報告後就會出現在這裡。</EmptyState>;
  }
  return (
    <section aria-labelledby="diamond-list-title" className="space-y-4">
      <h2 id="diamond-list-title" className="text-sm text-ink-700">
        共 <strong className="tabular-nums">{formatNumber(page.count)}</strong> 個組織
      </h2>
      <OrgRows orgs={page.results} />
      {lastPage > 1 && (
        <nav aria-label="分頁" className="flex items-center justify-between text-sm">
          {current > 1 ? (
            <Link href={pageHref(current - 1)} className="surface px-4 py-2 font-medium text-ink-800 hover:text-brand-800">
              ‹ 上一頁
            </Link>
          ) : (
            <span />
          )}
          <span className="tabular-nums text-ink-600">
            第 {formatNumber(current)} / {formatNumber(lastPage)} 頁
          </span>
          {current < lastPage ? (
            <Link href={pageHref(current + 1)} className="surface px-4 py-2 font-medium text-ink-800 hover:text-brand-800">
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
