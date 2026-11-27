import { EmptyState, TextLink } from "@/components/ui";

export default function DonorNotFound() {
  return (
    <EmptyState title="找不到這個捐款企業或團體">
      連結可能已失效。<TextLink href="/donors">回到捐款企業列表</TextLink>
    </EmptyState>
  );
}
