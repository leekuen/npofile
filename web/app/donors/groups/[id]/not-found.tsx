import { EmptyState, TextLink } from "@/components/ui";

export default function DonorGroupNotFound() {
  return (
    <EmptyState title="找不到這個集團">
      集團會隨董監事變動重新歸戶，連結可能已失效。<TextLink href="/donors?view=group">回到集團排行</TextLink>
    </EmptyState>
  );
}
