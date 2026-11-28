import Link from "next/link";

import { ApiUnavailableError, getStats } from "@/lib/server-api";

import { CountUp } from "./count-up";
import { ErrorBox, order, Skeleton } from "./ui";

// 第一格是「有紀錄可查」的組織，不是名冊上的全部（LK-46）；鑽石級那格連到專頁
const ITEMS = [
  { key: "with_data", label: "有紀錄可查的組織", href: undefined },
  { key: "diamond", label: "鑽石級組織", href: "/diamond" },
  { key: "penalized_5y", label: "近 5 年受裁罰", href: undefined },
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
    <dl className="grid grid-cols-3 gap-3 border-t border-ink-200/70 pt-5 lg:grid-cols-1 lg:content-center lg:gap-0 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-8">
      {ITEMS.map(({ key, label, href }, i) => (
        <div key={key} style={order(i + 2)} className="stagger animate-rise flex flex-col-reverse justify-end gap-0.5 lg:border-b lg:border-ink-200/70 lg:py-4 lg:first:pt-0 lg:last:border-b-0 lg:last:pb-0">
          <dt className="text-xs text-balance text-ink-600 lg:text-sm">
            {href ? (
              <Link href={href} className="text-brand-800 underline underline-offset-2 hover:text-brand-900">
                {label} ›
              </Link>
            ) : (
              label
            )}
          </dt>
          <dd className={`font-num text-xl font-bold tabular-nums sm:text-2xl lg:text-[1.75rem] lg:leading-tight ${key === "penalized_5y" ? "text-red-700" : "text-ink-900"}`}>
            <CountUp value={stats[key]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function StatsSkeleton() {
  return <Skeleton className="h-24 w-full" />;
}
