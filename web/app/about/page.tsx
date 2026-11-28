import type { Metadata } from "next";
import { type ReactNode, Suspense } from "react";

import { Card, Skeleton, TextLink } from "@/components/ui";
import { formatMoney } from "@/lib/format";
import { ApiUnavailableError, getStats } from "@/lib/server-api";

export const metadata: Metadata = { title: "資料說明" };

const SOURCES = [
  {
    name: "財政部非營利事業機關團體資料集",
    url: "https://eip.fia.gov.tw/data/BGMOPEN99.csv",
    what: "組織名冊：統一編號、名稱、縣市、營運狀態",
  },
  {
    name: "衛生福利部公益勸募管理系統",
    url: "https://sasw.mohw.gov.tw/app39/",
    what: "勸募團體的基本資料與年度募款、每一個勸募活動、活動公開的捐贈人清冊、違規公告（裁罰）",
  },
  {
    name: "經濟部商工登記公示資料",
    url: "https://data.gcis.nat.gov.tw/",
    what: "捐款企業的統一編號、代表人、資本額（名稱完全相同才對上）",
  },
  {
    name: "衛生福利部對民間團體及個人補(捐)助經費彙總表",
    url: "https://data.gov.tw/dataset/44952",
    what: "衛福部（含社會及家庭署等）每季公開的補助案件：補助機關、事項、核准日、金額（名稱完全相同才對上，附設單位算給上層法人）",
  },
  {
    name: "勞動部就業安定基金補(捐)助季報表",
    url: "https://data.gov.tw/dataset/128781",
    what: "就業安定基金（多元培力就業計畫、身障就業等）每季公開的補助案件，對組織的方式同上",
  },
  {
    name: "勞動部勞動力發展署及所屬補(捐)助經費季報表",
    url: "https://data.gov.tw/dataset/143623",
    what: "勞動力發展署與各分署的補助案件（公務預算與特別預算），對組織的方式同上；表上寫「對個人」的不收，跟就業安定基金重複列的只算一次",
  },
  {
    name: "教育部國民及學前教育署補(捐)助經費彙總表",
    url: "https://data.gov.tw/dataset/48670",
    what: "國教署每季公開的補助案件，對組織的方式同上",
  },
  {
    name: "新住民發展基金獎補助經費季報表",
    url: "https://data.gov.tw/dataset/86171",
    what: "新住民發展基金補助個人及團體的案件（不含補助縣市政府），對組織的方式同上",
  },
  {
    name: "海洋委員會主管預算補(捐)助經費彙總表",
    url: "https://data.gov.tw/dataset/139265",
    what: "海委會（含所屬機關）每季公開的補助案件，對組織的方式同上；民國 111、112 年只公開 PDF，沒有收錄",
  },
  {
    name: "臺北市政府勞動局違反勞動基準法事業單位公布總表",
    url: "https://data.gov.tw/dataset/121435",
    what: "勞動局依勞基法公布的處分（處分日期、文號、違反條款、罰鍰），只收非營利組織的，標示為「勞動法令」；負責人姓名不收",
  },
  {
    name: "挖貝 WaBay 群眾集資平台",
    url: "https://wabay.tw",
    what: "非營利組織提的集資專案（非政府資料，另外標示，不算進揭露層級與任何加總）",
  },
];

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="space-y-3">
      <h2 id={id} className="font-display text-xl font-bold text-ink-900">
        {title}
      </h2>
      <div className="space-y-3 text-sm leading-relaxed text-ink-800 sm:text-base">{children}</div>
    </section>
  );
}

export default function AboutPage() {
  return (
    <article className="mx-auto max-w-3xl space-y-10">
      <header className="space-y-2">
        <h1 className="font-display text-3xl font-extrabold text-ink-900">資料說明</h1>
        <p className="text-ink-700">這裡的資料都來自公開來源，每天凌晨更新一次。以下說明收了什麼、數字怎麼算。</p>
      </header>
      <Suspense fallback={<Skeleton className="h-96 w-full" />}>
        <AboutBody />
      </Suspense>
    </article>
  );
}

/** 期間的起始年度與個人捐款人門檻從後端讀（跟實際規則同一個來源）；讀不到就用不帶數字的寫法 */
async function AboutBody() {
  let since: number | null = null;
  let threshold: number | null = null;
  try {
    const stats = await getStats();
    since = stats.since_roc_year;
    threshold = stats.donor_individual_threshold;
  } catch (e) {
    if (!(e instanceof ApiUnavailableError)) throw e;
  }
  const window5 = since ? `近 5 年（民國 ${since} 年起）` : "近 5 年";

  return (
    <div className="space-y-10">
      <Section id="sources" title="資料從哪來">
        <ul className="space-y-3">
          {SOURCES.map((s) => (
            <li key={s.name}>
              <Card>
                <p className="font-semibold text-ink-900">
                  <TextLink href={s.url}>{s.name}</TextLink>
                </p>
                <p className="mt-1 text-sm text-ink-700">{s.what}</p>
              </Card>
            </li>
          ))}
        </ul>
        <p>資料以各來源公告為準。本站只整理、不改寫內容；發現與來源不符時，以來源為準。</p>
      </Section>

      <Section id="period" title="收哪些期間">
        <p>
          募款、勸募活動、捐款紀錄只收{window5}，比較有參考性，也讓頁面載入快。<strong className="font-semibold">裁罰紀錄全部年度都保留</strong>，不會因為時間過去而消失。
        </p>
      </Section>

      <Section id="score" title="揭露層級怎麼算">
        <p>
          揭露層級看組織在政府與公開來源上留下了多少看得到的資料，分四層，要依序達到：前一層達到了，下一層才算。
          每一條都是站上查得到來源的資料，不收組織自己填的內容。層級不是好壞評等，也不代表本站背書；受裁罰不影響層級，另外標示。
        </p>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[28rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-ink-200 text-left text-ink-600">
                <th scope="col" className="py-2 pr-4 font-medium">層級</th>
                <th scope="col" className="py-2 pr-4 font-medium">名稱</th>
                <th scope="col" className="py-2 font-medium">要有哪些資料（全部都要）</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100">
              <tr>
                <td className="py-2 pr-4 whitespace-nowrap tabular-nums">第 1 層</td>
                <td className="py-2 pr-4 whitespace-nowrap font-medium">身分可查</td>
                <td className="py-2">營運中，而且統一編號、團體類型、地址、宗旨（勸募用途或主管機關名冊的成立宗旨）、電話或官網都有</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 whitespace-nowrap tabular-nums">第 2 層</td>
                <td className="py-2 pr-4 whitespace-nowrap font-medium">活動可查</td>
                <td className="py-2">近 5 年有看得到的活動：政府許可的勸募活動、政府補助，或主管機關名冊上的主要業務。有辦勸募的，去年以前募到款的活動都要已向主管機關成果備查（今年的還在期限內，先不算）</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 whitespace-nowrap tabular-nums">第 3 層</td>
                <td className="py-2 pr-4 whitespace-nowrap font-medium">財務可查</td>
                <td className="py-2">最近兩個年度內有財務報告，至少看得到總收入與總支出</td>
              </tr>
              <tr>
                <td className="py-2 pr-4 whitespace-nowrap tabular-nums">第 4 層</td>
                <td className="py-2 pr-4 whitespace-nowrap font-medium">長期可查</td>
                <td className="py-2">連續 3 個年度都有財務報告、最近一年的財報經會計師查核，而且最近兩個年度內有年報或工作／成果報告</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-ink-600">還沒達到第 1 層的叫「資料不足」，多半是只有財政部名冊上的名稱與縣市。已註銷、撤銷或歇業的組織不分層級。群眾集資平台上的專案沒有政府的成果備查，不算勸募活動。</p>
      </Section>

      <Section id="categories" title="分類怎麼來">
        <p>
          大類先看衛福部登記的「勸募用途」。小類與服務對象（例：原住民、長者）是依組織名稱與近 5 年勸募活動的名稱推測的，畫面上會標「推測」，可能有誤。管理員修正過的分類，之後自動分類不會改掉。
        </p>
      </Section>

      <Section id="donors" title="捐款人與隱私">
        <ul className="list-disc space-y-2 pl-5">
          <li>企業與團體捐款人全部列出，可以看到捐給哪些組織、捐了多少。</li>
          <li>
            個人捐款人只在同一個勸募活動累計捐款達
            {threshold ? ` ${formatMoney(threshold)} ` : "門檻金額"}
            才顯示姓名，而且只出現在受捐組織的頁面；其餘只算人次與金額。
          </li>
          <li>匿名、「善心人士」，以及超商、電商、行動支付平台代收的小額捐款，不列名稱。</li>
          <li>收據編號不公開。</li>
        </ul>
      </Section>
    </div>
  );
}
