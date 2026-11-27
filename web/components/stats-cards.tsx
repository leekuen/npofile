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
    <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-600">
      {ITEMS.map(({ key, label }) => (
        <div key={key} className="flex items-baseline gap-1.5">
          <dt>{label}</dt>
          <dd className={`font-bold tabular-nums ${key === "penalized_5y" ? "text-red-800" : "text-slate-900"}`}>
            {formatNumber(stats[key])}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function StatsSkeleton() {
  return <Skeleton className="h-5 w-80 max-w-full" />;
}
