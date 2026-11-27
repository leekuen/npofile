import { Suspense } from "react";

import { DonorDetailSkeleton } from "@/components/donor-detail";
import { GroupDetailView } from "@/components/group-detail";

export default function DonorGroupPage({ params }: PageProps<"/donors/groups/[id]">) {
  return (
    <Suspense fallback={<DonorDetailSkeleton />}>
      <GroupDetailView params={params} />
    </Suspense>
  );
}
