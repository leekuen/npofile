import { Suspense } from "react";

import { CategoryOverviewSkeleton, CategoryOverviewView } from "@/components/category-overview";

export default function CategoryPage({ params }: PageProps<"/categories/[code]">) {
  return (
    <Suspense fallback={<CategoryOverviewSkeleton />}>
      <CategoryOverviewView params={params} />
    </Suspense>
  );
}
