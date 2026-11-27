import { Suspense } from "react";

import { OrgSearch, OrgSearchSkeleton } from "@/components/org-search";
import { StatsCards, StatsSkeleton } from "@/components/stats-cards";

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">查詢非營利組織</h1>
      <Suspense fallback={<StatsSkeleton />}>
        <StatsCards />
      </Suspense>
      <Suspense fallback={<OrgSearchSkeleton />}>
        <OrgSearch searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
