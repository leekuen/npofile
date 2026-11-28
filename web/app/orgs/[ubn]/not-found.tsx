import { EmptyState, TextLink } from "@/components/ui";

export default function OrgNotFound() {
  return (
    <EmptyState title="找不到這個組織">
      統一編號可能打錯，或這個組織還沒有被收錄。<TextLink href="/?mode=db">回到組織列表</TextLink>
    </EmptyState>
  );
}
