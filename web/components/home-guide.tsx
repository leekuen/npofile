import Link from "next/link";

import { formatNumber } from "@/lib/format";
import { ApiUnavailableError, getGuide } from "@/lib/server-api";

import { PickCard, pickItem, pickRow } from "./pick-card";
import { ErrorBox, order, Skeleton } from "./ui";

const link = "text-brand-800 underline underline-offset-2 hover:text-brand-950";

/** 首頁上方兩個模式（LK-51）：「幫我挑」（預設）｜「查資料庫」。用網址記住，可分享、上一頁回得來 */
export function ModeTabs({ mode }: { mode: "guide" | "db" }) {
  const tabs = [
    { key: "guide", label: "幫我挑", href: "/" },
    { key: "db", label: "查資料庫", href: "/?mode=db" },
  ] as const;
  return (
    <nav aria-label="首頁模式" className="flex justify-center">
      <ul className="inline-flex rounded-full bg-ink-100 p-1 text-sm font-medium">
        {tabs.map((t) => {
          const active = t.key === mode;
          return (
            <li key={t.key}>
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={`block rounded-full px-5 py-2 transition-colors ${
                  active ? "bg-white font-bold text-brand-900 shadow-sm" : "text-ink-700 hover:text-ink-900"
                }`}
              >
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function GuideIntro() {
  return (
    <section aria-labelledby="guide-title" className="surface animate-rise relative isolate overflow-hidden p-5 sm:p-8">
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
        <div className="hero-glow absolute -top-1/2 -left-1/4 h-[36rem] w-[56rem] max-w-none rounded-full bg-[radial-gradient(closest-side,var(--color-brand-100),transparent)] opacity-80" />
      </div>
      <h1 id="guide-title" className="font-display text-3xl leading-tight font-extrabold text-balance text-ink-900 sm:text-[2.5rem]">
        不知道捐給誰？
      </h1>
      <p className="mt-3 max-w-2xl text-base text-ink-800 sm:text-lg">先看看各領域裡資料公開得最齊、近五年沒有受裁罰的組織。</p>
      <p className="mt-1 text-sm text-ink-500">推薦只看資料公開了多少，不代表本站背書。</p>
    </section>
  );
}

/** 引導模式（LK-51）：每個公益大類一段，各推薦最多三個；0 個的大類只在最後列名稱 */
export async function HomeGuide() {
  let guide;
  try {
    guide = await getGuide();
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return (
        <div className="space-y-6">
          <GuideIntro />
          <ErrorBox title="目前讀不到推薦">
            資料服務暫時沒有回應，請稍後重新整理，或先到
            <Link href="/?mode=db" className="underline">
              查資料庫
            </Link>
            搜尋。
          </ErrorBox>
        </div>
      );
    }
    throw e;
  }
  return (
    <div className="space-y-10">
      <GuideIntro />
      {guide.fields.length === 0 && (
        <p className="surface p-5 text-sm text-ink-700">
          目前沒有符合條件的組織，可以到
          <Link href="/?mode=db" className={link}>
            查資料庫
          </Link>
          直接搜尋。
        </p>
      )}
      {guide.fields.map((f, i) => (
        <section key={f.code} aria-labelledby={`guide-${f.code}`} style={order(i)} className="stagger animate-rise space-y-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <h2 id={`guide-${f.code}`} className="font-display text-xl font-bold text-ink-900">
              {f.label}
              <span className="ml-2 text-sm font-normal tabular-nums text-ink-600">{formatNumber(f.count)} 個組織</span>
            </h2>
            <Link href={`/categories/${f.code}`} className={`text-sm font-medium ${link}`}>
              看這個領域全部 →
            </Link>
          </div>
          <ul className={pickRow}>
            {f.orgs.map((o) => (
              <li key={o.ubn} className={pickItem}>
                <PickCard o={o} penaltySources={guide.penalty_sources} />
              </li>
            ))}
          </ul>
        </section>
      ))}
      {guide.empty.length > 0 && (
        <p className="text-sm text-ink-600">這些領域目前沒有符合條件的組織：{guide.empty.map((e) => e.label).join("、")}</p>
      )}
    </div>
  );
}

export function HomeGuideSkeleton() {
  return (
    <div className="space-y-10" aria-hidden>
      <div className="surface space-y-3 p-5 sm:p-8">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-5 w-full max-w-xl" />
      </div>
      {[0, 1].map((i) => (
        <div key={i} className="space-y-3">
          <Skeleton className="h-6 w-40" />
          <div className="grid gap-3 lg:grid-cols-3">
            <Skeleton className="h-72" />
            <Skeleton className="hidden h-72 lg:block" />
            <Skeleton className="hidden h-72 lg:block" />
          </div>
        </div>
      ))}
    </div>
  );
}
