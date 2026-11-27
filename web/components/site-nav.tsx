"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  { href: "/", label: "組織", match: (p: string) => p === "/" || p.startsWith("/orgs") },
  { href: "/donors", label: "捐款企業", match: (p: string) => p.startsWith("/donors") },
  { href: "/about", label: "資料說明", match: (p: string) => p.startsWith("/about") },
];

function NavLinks({ pathname }: { pathname: string | null }) {
  return (
    <nav aria-label="主要">
      <ul className="flex gap-0.5 text-sm whitespace-nowrap sm:gap-1">
        {ITEMS.map((item) => {
          const active = pathname !== null && item.match(pathname);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-full px-2 py-2 sm:px-3 ${active ? "bg-brand-50 font-semibold text-brand-900" : "text-ink-700 hover:bg-ink-100"}`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** 讀網址決定哪一項亮起；Next 16 規定要包在 Suspense 裡，外面用 SiteNavFallback 當替身 */
export function SiteNav() {
  return <NavLinks pathname={usePathname()} />;
}

export function SiteNavFallback() {
  return <NavLinks pathname={null} />;
}
