import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { BadgeEmbed } from "@/components/badge-embed";
import { ErrorBox, LevelBadge, PageHeader, SectionHeading, Skeleton, TextLink } from "@/components/ui";
import { CHECK_GUIDE, CORRECTION_SOURCES, LEVEL_SUMMARY } from "@/lib/level-guide";
import { ApiUnavailableError, getOrg } from "@/lib/server-api";
import type { OrgDetail } from "@/lib/types";

export const metadata: Metadata = { title: "組織工具包" };

export default function KitPage({ params }: PageProps<"/orgs/[ubn]/kit">) {
  return (
    <Suspense fallback={<KitSkeleton />}>
      <KitView params={params} />
    </Suspense>
  );
}

async function KitView({ params }: { params: Promise<{ ubn: string }> }) {
  const { ubn } = await params;
  let org: OrgDetail | null;
  try {
    org = await getOrg(ubn);
  } catch (e) {
    if (e instanceof ApiUnavailableError) {
      return <ErrorBox title="目前讀不到這個組織的資料">資料服務暫時沒有回應，請稍後重新整理。</ErrorBox>;
    }
    throw e;
  }
  if (!org) notFound();

  return (
    <div className="space-y-8">
      <PageHeader
        crumbs={[
          { href: "/", label: "組織" },
          { href: `/orgs/${org.ubn}`, label: org.name },
          { label: "組織工具包" },
        ]}
        title="組織工具包"
        description={`給${org.name}的承辦人：把揭露徽章貼到官網，看看下一級還差哪些事。不用註冊，也不用填資料。`}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section aria-labelledby="badge" className="surface min-w-0 space-y-4 p-4 sm:p-5">
          <SectionHeading id="badge">你們的揭露徽章</SectionHeading>
          <BadgeEmbed ubn={org.ubn} orgName={org.name} />
          <p className="text-sm text-ink-600">
            徽章每天依公開資料自動更新，升級或降級都會跟著變。徽章只代表公開了多少資料，不代表本站背書或評價；點徽章會到你們在本站的組織頁，捐款人可以在那裡查證。
          </p>
        </section>

        <NextSteps org={org} />
      </div>

      <section aria-labelledby="fix" className="space-y-3">
        <SectionHeading id="fix">資料有錯？</SectionHeading>
        <p className="text-ink-700">
          本站的資料都來自政府或你們自己公開的來源，本站不能直接改。請到原始來源更正，下次抓取後這裡會自動更新。
        </p>
        <ul className="surface divide-y divide-ink-100">
          {CORRECTION_SOURCES.map((s) => (
            <li key={s.what} className="flex flex-col gap-0.5 px-4 py-3 text-sm sm:flex-row sm:gap-4 sm:px-5">
              <span className="font-medium text-ink-900 sm:w-64 sm:shrink-0">{s.what}</span>
              <TextLink href={s.where.href}>{s.where.label}</TextLink>
            </li>
          ))}
        </ul>
        <p className="text-sm text-ink-600">
          每一級的完整條件與做法見 <TextLink href="/for-orgs">給非營利組織</TextLink>。
        </p>
      </section>
    </div>
  );
}

/** 下一級還差哪幾條、每條怎麼做；更後面的層級只列名稱與一句話 */
function NextSteps({ org }: { org: OrgDetail }) {
  const lv = org.levels;
  const next = lv.layers.find((l) => l.level === lv.level + 1);
  const later = lv.layers.filter((l) => l.level > lv.level + 1);

  return (
    <section aria-labelledby="next" className="surface min-w-0 space-y-4 p-4 sm:p-5">
      <SectionHeading id="next">下一級還差什麼</SectionHeading>
      {lv.active && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-ink-600">目前</span>
          <LevelBadge level={lv.level} size="lg" />
        </div>
      )}

      {!lv.active ? (
        <p className="text-ink-800">
          這個組織目前是「{org.status_label}」，不分層級。若仍在運作，請先向所在地國稅局確認稅籍登記。
        </p>
      ) : !next ? (
        <p className="text-ink-800">已經是最高一級。記得每年持續公開財務報告與年報，層級才會維持。</p>
      ) : (
        <>
          <p className="text-ink-800">
            升到「{next.medal}・{next.name}」還差這幾件事：
          </p>
          <ol className="space-y-3">
            {next.checks
              .filter((c) => !c.met)
              .map((c, i) => {
                const g = CHECK_GUIDE[c.key];
                return (
                  <li key={c.key} className="rounded-xl bg-sun-50 p-3.5 ring-1 ring-sun-100">
                    <p className="font-medium text-ink-900">
                      {i + 1}. {c.label}
                      {c.hint && <span className="ml-1 font-normal text-ink-600">（{c.hint}）</span>}
                    </p>
                    {g && <p className="mt-1 text-sm text-ink-700">{g.how}</p>}
                    {g?.links && g.links.length > 0 && (
                      <p className="mt-1.5 flex flex-wrap gap-x-4 text-sm">
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
          </ol>
        </>
      )}

      {lv.active && later.length > 0 && (
        <div className="border-t border-ink-100 pt-3">
          <p className="text-sm font-medium text-ink-700">再往上</p>
          <ul className="mt-1 space-y-1 text-sm text-ink-600">
            {later.map((l) => (
              <li key={l.level}>
                <span className="font-medium text-ink-800">
                  {l.medal}・{l.name}
                </span>
                ：{LEVEL_SUMMARY[l.level]}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function KitSkeleton() {
  return (
    <div className="space-y-8">
      <Skeleton className="h-10 w-48" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
    </div>
  );
}
