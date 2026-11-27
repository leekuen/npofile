import { EmptyState, TextLink } from "@/components/ui";

export default function CategoryNotFound() {
  return (
    <EmptyState title="沒有這個分類">
      <TextLink href="/">回到首頁依領域瀏覽</TextLink>
    </EmptyState>
  );
}
