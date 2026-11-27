import { formatNumber } from "@/lib/format";
import { ApiUnavailableError, getStats } from "@/lib/server-api";

import { ErrorBox, Skeleton } from "./ui";

const ITEMS = [
  { key: "organizations", label: "收錄組織" },
  { key: "with_fundraising", label: "近 5 年有公益勸募紀錄" },
  { key: "penalized_5y", label: "近五年受裁罰" },
] as const;

/** 首頁搜尋框下方的一行統計：數字是背景資訊，不搶搜尋框 */
export async function StatsCards() {
  let stats;
  try {
    stats = await getStats();
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前讀不到資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  return (
    <dl className="grid grid-cols-3 gap-3 border-t border-ink-100 pt-5 lg:grid-cols-1 lg:gap-0 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-8">
      {ITEMS.map(({ key, label }) => (
        <div key={key} className="flex flex-col justify-between lg:flex-row lg:items-baseline lg:justify-between lg:gap-3 lg:border-b lg:border-dashed lg:border-ink-200 lg:py-3 lg:last:border-b-0">
          <dt className="text-xs text-ink-600 lg:text-sm">{label}</dt>
          <dd className={`font-num text-lg font-semibold tabular-nums lg:text-xl ${key === "penalized_5y" ? "text-red-700" : "text-ink-900"}`}>
            {formatNumber(stats[key])}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function StatsSkeleton() {
  return <Skeleton className="h-24 w-full" />;
}
