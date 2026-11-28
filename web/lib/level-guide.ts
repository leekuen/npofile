/**
 * 揭露層級升級指南（LK-42）：每一個條件「組織要去哪裡、做什麼」。
 * 條件代號跟後端 server/orgs/scoring.py 的 levels() 一樣；後端加條件時，
 * server/orgs/tests/test_badge.py 會檢查這裡有沒有對應的文字。
 */

export interface GuideLink {
  label: string;
  href: string;
}

export interface CheckGuide {
  /** 給組織看的一句話：要做什麼 */
  how: string;
  links?: GuideLink[];
}

const FIA: GuideLink = { label: "財政部稅務入口網", href: "https://www.etax.nat.gov.tw/" };
const MOHW: GuideLink = { label: "衛福部公益勸募管理系統", href: "https://sasw.mohw.gov.tw/app39/" };

export const CHECK_GUIDE: Record<string, CheckGuide> = {
  active: {
    how: "營運狀態來自財政部的非營利事業名冊。若組織仍在運作卻顯示停業或註銷，請向所在地國稅局確認稅籍登記。",
    links: [FIA],
  },
  ubn: {
    how: "向國稅局辦理稅籍登記取得統一編號；本站用統一編號辨識組織。",
    links: [FIA],
  },
  org_type: {
    how: "團體類型（財團法人、社團法人等）來自衛福部公益勸募系統或主管機關名冊；辦過公益勸募、或在教育部等主管機關名冊上，就會有。",
    links: [MOHW],
  },
  address: {
    how: "登記地址或聯絡地址來自衛福部公益勸募系統或主管機關名冊；請確認在主管機關登記的地址是最新的。",
    links: [MOHW],
  },
  purpose: {
    how: "宗旨來自勸募活動的「勸募用途」或主管機關名冊上的「成立宗旨」；申請勸募許可時寫清楚用途即可。",
    links: [MOHW],
  },
  contact: {
    how: "電話或官網來自衛福部公益勸募系統；在系統的團體資料填上電話與官網網址，捐款人才找得到你們。",
    links: [MOHW],
  },
  activity: {
    how: "近 5 年要有一項看得到的活動：辦過衛福部許可的公益勸募、拿過政府補助，或在主管機關名冊上寫了主要業務，任一項都算。",
    links: [MOHW],
  },
  results_filed: {
    how: "勸募活動期滿後 30 日內，要在衛福部公益勸募管理系統上傳收支報告與捐贈人資料（成果備查，公益勸募條例第 18 條）；錢用完後 30 日內再交結案備查（第 20 條）。期限已過、募到款的活動都要交，逾期補交也算。",
    links: [MOHW],
  },
  financial_recent: {
    how: "在官網公開最近兩個年度內的財務報告（PDF 即可，要看得到總收入與總支出），本站會定期到官網抓；社福財團法人在衛福部公開的決算、加入台灣公益團體自律聯盟並公開財報也算。",
    links: [{ label: "台灣公益團體自律聯盟", href: "https://www.twnpos.org.tw/" }],
  },
  financial_consecutive: {
    how: "連續 3 個年度都公開財務報告，不要只放最新一年；舊年度的報告請留在官網上。",
  },
  report: {
    how: "在官網公開最近兩個年度內的年報、工作報告或成果報告，說明這一年做了什麼、幫了多少人。",
  },
};

/** 每一級給組織看的一句說明（工具包「之後的層級」與給組織頁用） */
export const LEVEL_SUMMARY: Record<number, string> = {
  1: "查得到你們是誰：營運中、有統編、類型、地址、宗旨與聯絡方式。",
  2: "查得到你們在做什麼：近 5 年有活動，往年的勸募都已交代成果。",
  3: "查得到你們的錢：最近兩年內公開過財務報告。",
  4: "查得到你們長期的樣子：連續 3 年財報，也公開年報或成果報告。",
};

/** 每一級的條件代號（順序跟後端一樣；給組織頁不必呼叫 API 就能列出條件） */
export const LEVEL_CHECKS: Record<number, { key: string; label: string }[]> = {
  1: [
    { key: "active", label: "營運中" },
    { key: "ubn", label: "統一編號" },
    { key: "org_type", label: "團體類型" },
    { key: "address", label: "地址" },
    { key: "purpose", label: "宗旨或勸募用途" },
    { key: "contact", label: "電話或官網" },
  ],
  2: [
    { key: "activity", label: "近 5 年有看得到的活動" },
    { key: "results_filed", label: "到期的勸募活動都已成果備查" },
  ],
  3: [{ key: "financial_recent", label: "最近兩個年度內的財務報告" }],
  4: [
    { key: "financial_consecutive", label: "連續 3 個年度的財務報告" },
    { key: "report", label: "最近兩個年度內的年報或工作／成果報告" },
  ],
};

/** 資料有錯時要去哪裡更正 */
export const CORRECTION_SOURCES: { what: string; where: GuideLink }[] = [
  { what: "名稱、統一編號、營運狀態", where: { label: "財政部非營利事業名冊（所在地國稅局）", href: "https://www.etax.nat.gov.tw/" } },
  { what: "團體資料、勸募活動、成果備查、捐贈人清冊、裁罰", where: MOHW },
  { what: "主管機關、宗旨、主要業務、財產總額", where: { label: "各主管機關的財團法人名冊（例：教育部）", href: "https://data.gov.tw/" } },
  { what: "政府補助", where: { label: "補助機關每季公開的補(捐)助季報", href: "https://data.gov.tw/" } },
  { what: "財務報告、年報", where: { label: "你們自己的官網（本站定期去抓）", href: "/about#sources" } },
];

/** 嵌入程式碼用的正式網址：有設 NEXT_PUBLIC_SITE_URL 就用它，否則交給呼叫端用目前網址 */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL ?? "").replace(/\/$/, "");
