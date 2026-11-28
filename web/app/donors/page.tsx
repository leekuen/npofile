import type { Metadata } from "next";
import { Suspense } from "react";

import { DonorSearch, DonorSearchSkeleton } from "@/components/donor-search";
import { PageHeader } from "@/components/ui";

export const metadata: Metadata = { title: "捐款企業" };

export default function DonorsPage({ searchParams }: PageProps<"/donors">) {
  return (
    <div className="space-y-8">
      <PageHeader title="捐款企業與團體" description="依近 5 年各勸募活動公開的捐贈人清冊彙整。" />
      <Suspense fallback={<DonorSearchSkeleton />}>
        <DonorSearch searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
