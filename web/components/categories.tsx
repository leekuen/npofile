import Link from "next/link";

import { formatNumber } from "@/lib/format";
import type { CategoryTag, OrgCategories, Taxonomy } from "@/lib/types";

/** 推測的分類用虛線框＋「推測」字樣，跟官方分得出來（不只靠顏色）。 */
export function CategoryChip({ tag, link = true }: { tag: CategoryTag; link?: boolean }) {
  const inferred = tag.source === "inferred";
  const cls = `inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs ${
    inferred ? "border border-dashed border-slate-400 text-slate-700" : "border border-teal-600/40 bg-teal-50 text-teal-900"
  }`;
  const body = (
    <>
      {tag.label}
      {inferred && <span className="text-[10px] text-slate-500">推測</span>}
    </>
  );
  if (!link) {
    return <span className={cls}>{body}</span>;
  }
  return (
    <Link href={`/categories/${tag.code}`} className={`${cls} hover:underline`} title={inferred ? "依名稱推測，可能有誤" : "官方勸募用途"}>
      {body}
    </Link>
  );
}

export function OrgCategoryTags({ categories }: { categories: OrgCategories }) {
  if (!categories.fields.length && !categories.targets.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="分類">
      {categories.fields.map((f) => (
        <span key={f.code} className="inline-flex flex-wrap items-center gap-1">
          <CategoryChip tag={f} />
          {f.subs.map((s) => (
            <CategoryChip key={s.code} tag={s} />
          ))}
        </span>
      ))}
      {categories.targets.length > 0 && <span className="mx-1 text-xs text-slate-500">服務對象</span>}
      {categories.targets.map((t) => (
        <CategoryChip key={t.code} tag={t} />
      ))}
    </div>
  );
}

/** 首頁：依大類瀏覽（膠囊），選了大類才展開小類（底線文字，跟大類是不同家族的元件）。 */
export function CategoryBrowser({
  taxonomy,
  field,
  sub,
  hrefFor,
}: {
  taxonomy: Taxonomy;
  field: string;
  sub: string;
  hrefFor: (patch: { field?: string; sub?: string }) => string;
}) {
  const selected = taxonomy.fields.find((f) => f.code === field);
  return (
    <nav aria-label="依領域瀏覽" className="space-y-2">
      {/* 手機一排橫滑，不要把列表推到很下面；寬螢幕自動換行 */}
      <ul className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0">
        {taxonomy.fields.map((f) => {
          const active = f.code === field;
          const muted = f.code === "other";
          return (
            <li key={f.code} className="shrink-0">
              <Link
                href={hrefFor(active ? { field: "", sub: "" } : { field: f.code, sub: "" })}
                aria-current={active ? "true" : undefined}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm ${
                  active
                    ? "border-teal-700 bg-teal-700 text-white"
                    : muted
                      ? "border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100"
                      : "border-slate-300 bg-white text-slate-800 hover:border-teal-600"
                }`}
              >
                {f.label}
                <span className={`tabular-nums text-xs ${active ? "text-teal-100" : "text-slate-500"}`}>
                  {formatNumber(f.count)}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      {selected && selected.subs.length > 0 && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 border-l-2 border-teal-700 pl-3 text-sm">
          {selected.subs.map((s) => {
            const active = s.code === sub;
            return (
              <li key={s.code}>
                <Link
                  href={hrefFor({ field: selected.code, sub: active ? "" : s.code })}
                  aria-current={active ? "true" : undefined}
                  className={active ? "font-semibold text-teal-900 underline underline-offset-4" : "text-slate-700 hover:text-teal-900 hover:underline"}
                >
                  {s.label} <span className="tabular-nums text-xs text-slate-500">{formatNumber(s.count)}</span>
                </Link>
              </li>
            );
          })}
          <li>
            <Link href={`/categories/${sub || selected.code}`} className="text-teal-800 underline underline-offset-2">
              看「{selected.subs.find((s) => s.code === sub)?.label ?? selected.label}」領域總覽 ›
            </Link>
          </li>
        </ul>
      )}
    </nav>
  );
}
