import type { Metadata } from "next";
import { Suspense } from "react";

import { DonorSearch, DonorSearchSkeleton } from "@/components/donor-search";

export const metadata: Metadata = { title: "捐款企業" };

export default function DonorsPage({ searchParams }: PageProps<"/donors">) {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">捐款企業與團體</h1>
        <p className="mt-1 text-sm text-slate-600">依近 5 年各勸募活動公開的捐贈人清冊彙整。</p>
      </div>
      <Suspense fallback={<DonorSearchSkeleton />}>
        <DonorSearch searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
