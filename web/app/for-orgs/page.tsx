import type { Metadata } from "next";

import { LevelBadge, PageHeader, SectionHeading, TextLink } from "@/components/ui";
import { CHECK_GUIDE, LEVEL_CHECKS, LEVEL_SUMMARY } from "@/lib/level-guide";

export const metadata: Metadata = { title: "給非營利組織" };

const LEVELS = [1, 2, 3, 4];

const FAQ = [
  {
    q: "要註冊或付費嗎？",
    a: "不用。本站只整理政府與公開來源的資料，組織不必註冊、不必填表，也不收任何費用。",
  },
  {
    q: "可以自己改本站上的資料嗎？",
    a: "不行，本站也不能直接改。資料有錯請到原始來源更正（例：衛福部公益勸募管理系統、國稅局），下次抓取後會自動更新。這樣捐款人才能相信：站上看到的，都查得到出處。",
  },
  {
    q: "徽章會變嗎？",
    a: "會。每天依公開資料重算，公開的資料變多就升級；例如財務報告超過兩年沒更新，就會降回去。貼一次程式碼，之後不用再換。",
  },
  {
    q: "被裁罰會降級嗎？",
    a: "不會。層級只回答「公開了多少」，不評好壞；裁罰紀錄在組織頁另外標示，所有年度都保留。",
  },
  {
    q: "徽章代表本站認證嗎？",
    a: "不代表。徽章只說明這個組織在公開來源上留下了多少看得到的資料，不是背書或評價。點徽章會回到本站的組織頁，捐款人可以自己查證每一條。",
  },
];

export default function ForOrgsPage() {
  return (
    <div className="space-y-10">
      <PageHeader
        title="給非營利組織"
        description="捐款人在這裡查你們的募款、補助、財報與裁罰紀錄。資料全部來自政府與你們自己公開的來源，不用註冊，也不用填資料。"
      />

      <section aria-labelledby="get" className="surface space-y-3 p-4 sm:p-5">
        <SectionHeading id="get">拿到你們的揭露徽章</SectionHeading>
        <p className="text-ink-700">
          找到你們的組織頁，點「你是這個組織？」就有可以貼到官網的徽章程式碼，也會列出下一級還差哪些事。
        </p>
        <form action="/" method="get" role="search" className="flex max-w-xl gap-2">
          <label htmlFor="for-orgs-q" className="sr-only">
            組織名稱或統一編號
          </label>
          <input
            id="for-orgs-q"
            name="q"
            required
            placeholder="組織名稱或統一編號"
            className="min-h-11 min-w-0 flex-1 rounded-lg bg-white px-3 ring-1 ring-ink-300 focus:ring-2 focus:ring-brand-600 focus:outline-none"
          />
          <button type="submit" className="min-h-11 shrink-0 rounded-lg bg-sun-400 px-5 font-medium text-ink-900 hover:bg-sun-500">
            搜尋
          </button>
        </form>
        <p className="text-sm text-ink-600">
          工具包網址是 <code className="font-mono text-xs">/orgs/統一編號/kit</code>。
        </p>
      </section>

      <section aria-labelledby="levels" className="space-y-4">
        <SectionHeading id="levels">每一級要做到什麼</SectionHeading>
        <p className="text-ink-700">
          四級要依序達到：前一級達到了，下一級才算。每一條都看政府或公開來源上的資料，所以要升級，就是把該公開的資料公開在下面這些地方。算法細節見{" "}
          <TextLink href="/about#score">資料說明</TextLink>。
        </p>
        <ol className="space-y-4">
          {LEVELS.map((n) => (
            <li key={n} className="surface p-4 sm:p-5">
              <div className="flex flex-wrap items-center gap-3">
                <LevelBadge level={n} size="lg" />
                <p className="text-sm text-ink-700">{LEVEL_SUMMARY[n]}</p>
              </div>
              <ul className="mt-3 divide-y divide-ink-100">
                {LEVEL_CHECKS[n].map((c) => {
                  const g = CHECK_GUIDE[c.key];
                  return (
                    <li key={c.key} className="py-2.5 text-sm">
                      <p className="font-medium text-ink-900">{c.label}</p>
                      <p className="mt-0.5 text-ink-700">{g.how}</p>
                      {g.links && (
                        <p className="mt-1 flex flex-wrap gap-x-4">
                          {g.links.map((l) => (
                            <TextLink key={l.href} href={l.href}>
                              {l.label}
                            </TextLink>
                          ))}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="faq" className="space-y-3">
        <SectionHeading id="faq">常見問題</SectionHeading>
        <dl className="surface divide-y divide-ink-100">
          {FAQ.map((f) => (
            <div key={f.q} className="px-4 py-3.5 sm:px-5">
              <dt className="font-medium text-ink-900">{f.q}</dt>
              <dd className="mt-1 text-sm text-ink-700">{f.a}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
