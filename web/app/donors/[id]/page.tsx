import { Suspense } from "react";

import { DonorDetailSkeleton, DonorDetailView } from "@/components/donor-detail";

export default function DonorPage({ params }: PageProps<"/donors/[id]">) {
  return (
    <Suspense fallback={<DonorDetailSkeleton />}>
      <DonorDetailView params={params} />
    </Suspense>
  );
}
