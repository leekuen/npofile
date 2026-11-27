import { Suspense } from "react";

import { OrgSearch, OrgSearchSkeleton } from "@/components/org-search";
import { StatsCards, StatsSkeleton } from "@/components/stats-cards";

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<OrgSearchSkeleton />}>
      <OrgSearch
        searchParams={searchParams}
        stats={
          <Suspense fallback={<StatsSkeleton />}>
            <StatsCards />
          </Suspense>
        }
      />
    </Suspense>
  );
}
