import { Suspense } from "react";

import { OrgDetailSkeleton, OrgDetailView } from "@/components/org-detail";

export default function OrgPage({ params, searchParams }: PageProps<"/orgs/[ubn]">) {
  return (
    <Suspense fallback={<OrgDetailSkeleton />}>
      <OrgDetailView params={params} searchParams={searchParams} />
    </Suspense>
  );
}
