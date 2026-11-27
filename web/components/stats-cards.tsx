import { formatNumber } from "@/lib/format";
import { ApiUnavailableError, getStats } from "@/lib/server-api";

import { Card, ErrorBox, Skeleton } from "./ui";

const ITEMS = [
  { key: "organizations", label: "收錄組織數" },
  { key: "with_fundraising", label: "有公益勸募紀錄的組織" },
  { key: "penalized_5y", label: "近五年受裁罰的組織" },
] as const;

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
    <dl className="grid grid-cols-3 gap-2 sm:gap-3">
      {ITEMS.map(({ key, label }) => (
        <Card key={key} className="flex flex-col justify-between p-3">
          <dt className="text-xs text-slate-600 sm:text-sm">{label}</dt>
          <dd className={`mt-1 text-lg font-bold tabular-nums sm:text-2xl ${key === "penalized_5y" ? "text-red-800" : "text-slate-900"}`}>
            {formatNumber(stats[key])}
          </dd>
        </Card>
      ))}
    </dl>
  );
}

export function StatsSkeleton() {
  return (
    <div className="grid grid-cols-3 gap-2 sm:gap-3">
      {ITEMS.map(({ key }) => (
        <Card key={key} className="p-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="mt-2 h-7 w-20" />
        </Card>
      ))}
    </div>
  );
}
