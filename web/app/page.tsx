import { Suspense } from "react";

import { HomeGuide, HomeGuideSkeleton, ModeTabs } from "@/components/home-guide";
import { OrgSearch, OrgSearchSkeleton } from "@/components/org-search";
import { StatsCards, StatsSkeleton } from "@/components/stats-cards";

type Search = Record<string, string | string[] | undefined>;

/** 網址帶這些參數（有值沒值都算）就是查資料庫模式：舊連結（搜尋、篩選、排序、分頁）照舊（LK-51） */
const DB_PARAMS = ["q", "city", "status", "ordering", "field", "sub", "target", "page"];

function isDbMode(sp: Search) {
  return sp.mode === "db" || DB_PARAMS.some((k) => k in sp);
}

export default function Home({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<HomeGuideSkeleton />}>
      <HomeBody searchParams={searchParams} />
    </Suspense>
  );
}

async function HomeBody({ searchParams }: { searchParams: Promise<Search> }) {
  const db = isDbMode(await searchParams);
  return (
    <div className="space-y-6">
      <ModeTabs mode={db ? "db" : "guide"} />
      {db ? (
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
      ) : (
        <HomeGuide />
      )}
    </div>
  );
}
