export type OrgStatus = "active" | "cancelled" | "revoked" | "closed";

export interface OrgSummary {
  ubn: string;
  name: string;
  org_type: string;
  city: string;
  status: OrgStatus;
  status_label: string;
  disclosure_level: number;
  penalty_count_5y: number;
  public_raised_5y: number;
  tags: CategoryTag[];
  /** 近 5 年內有總收入的最近一年（LK-17）；列表 API 才有，沒有財務數字是 null */
  latest_revenue?: { year: number; total_revenue: number } | null;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Stats {
  organizations: number;
  /** 組織頁上有任一種紀錄（勸募、集資、補助、財報、年報、捐款、裁罰）的組織數（LK-46） */
  with_data: number;
  /** 鑽石級（揭露層級 4）組織數（LK-46） */
  diamond: number;
  with_fundraising: number;
  penalized_5y: number;
  since_roc_year: number;
  /** 個人捐款人在同一活動累計達這個金額才顯示姓名（元） */
  donor_individual_threshold: number;
}

export interface Filters {
  cities: string[];
  statuses: { value: OrgStatus; label: string }[];
}

export interface SourceLink {
  name: string;
  url: string;
}

export interface Annual {
  year: number;
  raised: number;
  target: number;
  achievement_rate: number | null;
  source_name: string;
  source_url: string;
}

export interface Project {
  id: number;
  /** 來源上的編號（衛福部活動編號）：首頁的卡片連到 `?tab=projects#p-<這個>`（LK-18） */
  external_id: string;
  name: string;
  category: string;
  start_date: string | null;
  end_date: string | null;
  target: number | null;
  raised: number | null;
  permit_no: string;
  region: string;
  result_filed_on: string | null;
  closed_filed_on: string | null;
  /** 活動頁的備查狀態（LK-43）：期限是法定期限；done＝已備查（null＝沒讀過活動頁）；late＝活動頁標「逾期備查」 */
  result_due_on: string | null;
  result_done: boolean | null;
  result_late: boolean;
  closed_due_on: string | null;
  closed_done: boolean | null;
  closed_late: boolean;
  description: string;
  source_name: string;
  source_url: string;
  /** permit＝衛福部勸募活動；crowdfunding＝群眾集資（挖貝，LK-15） */
  channel: "permit" | "crowdfunding";
  monthly_raised: number | null;
  backers: number | null;
}

export interface Penalty {
  id: number;
  decided_on: string | null;
  authority: string;
  document_no: string;
  content: string;
  fine_text: string;
  reason: string;
  source_name: string;
  source_url: string;
  /** 類別（LK-36 起存在資料表）：labor 勞動法令、fundraising 公益勸募、environment 環境保護、procurement 政府採購停權 */
  category: "labor" | "fundraising" | "environment" | "procurement";
  /** 違反法條（例：廢棄物清理法第27條第11款）；沒有就是空字串 */
  law: string;
}

export type DonorKind = "company" | "group" | "individual";

export interface DonationRow {
  id: number;
  donor_name: string;
  donor_id: number | null;
  donor_kind: DonorKind | null;
  purpose: string;
  amount: number;
  /** 金額讀不出確定數字時的原文（LK-49，例「新台幣20-30萬元」）；有值就顯示它、不算進加總 */
  amount_note: string;
  donated_on: string | null;
  /** 財團法人年度捐贈名單清冊（LK-48）只有年度（民國）、沒有日期；其他是 null */
  year: number | null;
  source_name: string;
  source_url: string;
}

/** 揭露層級（LK-35）：四層依序達成，每一層的條件全部達到才算 */
export interface LevelCheck {
  key: string;
  label: string;
  met: boolean;
  /** 補充說明，例如「已備查 3／4」；沒有是空字串 */
  hint: string;
}

export interface LevelLayer {
  level: number;
  /** 銅、銀、金、鑽石 */
  medal: string;
  name: string;
  met: boolean;
  checks: LevelCheck[];
}

export interface DisclosureLevels {
  level: number;
  /** 未分級、銅、銀、金、鑽石 */
  medal: string;
  name: string;
  max_level: number;
  active: boolean;
  layers: LevelLayer[];
  results_due: number;
  results_filed: number;
}

/** 一個會計年度的財務摘要（LK-17，參照 Candid Financials）；金額單位元，報告沒列的是 null */
export interface FinancialYear {
  year: number;
  total_revenue: number | null;
  contributions: number | null;
  government_grants: number | null;
  program_service_revenue: number | null;
  investment_income: number | null;
  other_revenue: number | null;
  total_expenses: number | null;
  program_expenses: number | null;
  admin_expenses: number | null;
  fundraising_expenses: number | null;
  surplus: number | null;
  total_assets: number | null;
  total_liabilities: number | null;
  net_assets: number | null;
  program_expense_ratio: number | null;
  audited: boolean | null;
  method: "ai" | "manual" | "official" | "text" | "ocr";
  document_url: string;
  document_title: string;
}

export interface OrgDocument {
  id: number;
  year: number;
  kind: "financial" | "annual" | "work";
  kind_label: string;
  title: string;
  url: string;
  found_on: string;
}

/** 近 5 年公開募款（LK-20）：勸募申報＋群眾集資；勸募已申報的年度不再加當年集資 */
export interface PublicRaised {
  total: number;
  permit: number;
  crowdfunding: number;
  crowdfunding_counted: number;
}

/** 政府對民間團體的補(捐)助（LK-19）：金額是核定金額（含累積） */
/** 司法院法人登記公告（LK-31）：只有組織層級的欄位 */
export type CourtCaseType = "setup" | "change" | "dissolution" | "liquidator" | "liquidation_end";

export interface CourtRegistration {
  id: number;
  posted_on: string | null;
  registered_on: string | null;
  court: string;
  case_no: string;
  reg_no: string;
  category: "association" | "foundation" | "";
  category_label: string;
  case_type: CourtCaseType;
  case_label: string;
  property_total: number | null;
  change_items: string[];
  source_name: string;
  source_url: string;
}

export interface CourtDissolution {
  posted_on: string | null;
  registered_on: string | null;
  court: string;
  case_type: "dissolution" | "liquidation_end";
  case_label: string;
  source_url: string;
}

export interface Grant {
  id: number;
  year: number;
  quarter: number;
  agency: string;
  county: string;
  recipient: string;
  facility: string;
  purpose: string;
  approved_on: string | null;
  amount: number;
  source_name: string;
  source_url: string;
}

export interface DonationTrendRow {
  year: number;
  permit: number;
  crowdfunding: number;
  grants: number;
}

/** 主管機關名冊（LK-32）：名稱對到這個組織的那一列；個人姓名與聯絡方式不存 */
export interface RegistryEntry {
  authority: string;
  registry_name: string;
  permit_no: string;
  founded_on: string | null;
  registered_assets: number | null;
  status: string;
  service_targets: string;
  business_category: string;
  /** 資料集最近更新日 */
  data_date: string | null;
  source_name: string;
  source_url: string;
}

/** 組織理念（LK-54）：一句話介紹＋宗旨原文。優先順序：管理員改過 > 主管機關名冊 > 組織官網（核准後） */
export interface OrgMission {
  /** 40 字內，顯示在組織名稱下方與推薦卡 */
  summary: string;
  text: string;
  origin: "manual" | "registry" | "website";
  /** 原文出處的名稱：「教育部名冊」「組織官網」「本站整理」 */
  origin_label: string;
  source_name: string;
  source_url: string;
  summary_method: "claude" | "first_sentence" | "manual";
  /** 一句話是本站濃縮的（不是組織自己那一句）：旁邊要標「由本站摘要」 */
  summarized_by_site: boolean;
  fetched_on: string | null;
}

/** 電子發票捐贈碼（LK-32）：用統編對到這個組織 */
export interface DonationCode {
  code: string;
  short_name: string;
  source_name: string;
  source_url: string;
}

export interface OrgDetail extends Omit<OrgSummary, "public_raised_5y"> {
  public_raised: PublicRaised;
  representative: string;
  registered_address: string;
  contact_address: string;
  phone: string;
  website: string;
  purposes: string;
  source_links: SourceLink[];
  levels: DisclosureLevels;
  annual_records: Annual[];
  financials: FinancialYear[];
  documents: OrgDocument[];
  projects: Project[];
  penalties: Penalty[];
  /** 政府補助（LK-19），近 5 年，金額大的在前 */
  grants: Grant[];
  /** 近 5 年受捐款趨勢（LK-33）：每年勸募實募、群眾集資、政府補助（元），不相加；今年都是 0 時不列 */
  donation_trend: DonationTrendRow[];
  court_registrations: CourtRegistration[];
  court_dissolution: CourtDissolution | null;
  /** 主管機關名冊與發票捐贈碼（LK-32）：沒有資料是空陣列 */
  registries: RegistryEntry[];
  donation_codes: DonationCode[];
  donations: DonationRow[];
  corporate_donors: CorporateDonorRank[];
  individual_donors: { name: string; total: number; count: number }[];
  donor_summary: DonorSummary | null;
  /** 官網公開的年度捐贈名單清冊（LK-48），近 5 年 */
  annual_donor_lists: AnnualDonorListLink[];
  since_roc_year: number;
  categories: OrgCategories;
  /** 沒有理念是 null */
  mission: OrgMission | null;
  updated_at: string;
}

export interface Me {
  email: string;
  display_name: string;
  is_staff: boolean;
}

export interface CommentRow {
  id: number;
  author_name: string;
  body: string;
  status: "pending" | "approved" | "rejected";
  status_label: string;
  reject_reason: string;
  created_at: string;
  is_mine: boolean;
}

export interface ApiErrorBody {
  error: { code: string; message: string; fields: Record<string, string[]> };
}

export interface CorporateDonorRank {
  donor_id: number;
  name: string;
  kind: "company" | "group";
  kind_label: string;
  ubn: string;
  total: number;
  count: number;
  /** 金額來自哪幾份清冊（衛福部勸募清冊、財團法人年度清冊…，LK-48） */
  sources: string[];
}

export interface AnnualDonorListLink {
  year: number;
  direction: "receive" | "pay";
  direction_label: string;
  title: string;
  url: string;
  /** 掃描檔：還沒讀出名單 */
  scanned: boolean;
  kept_rows: number;
}

export interface DonorSummary {
  lists: number;
  total_rows: number;
  total_amount: number;
  small_individual_count: number;
  small_individual_amount: number;
  anonymous_rows: number;
  anonymous_amount: number;
  threshold: number;
}

export interface DonorSummaryRow {
  id: number;
  name: string;
  kind: "company" | "group";
  kind_label: string;
  ubn: string;
  total: number;
  org_count: number;
  donation_count: number;
  /** 近 5 年有捐款的年度數（有日期、不晚於今天的才算；LK-38） */
  active_year_count: number;
  last_donated_on: string | null;
}

export interface DonorYear {
  /** 民國年 */
  year: number;
  total: number;
  org_count: number;
  count: number;
}

export interface DonorOverview {
  /** 同類（企業或團體）依近 5 年總額的名次，同額同名次 */
  rank: number;
  rank_of: number;
  active_years: number[];
  first_donated_on: string | null;
  last_donated_on: string | null;
  max_donation: number;
  yearly: DonorYear[];
}

export interface DonorDetail extends DonorSummaryRow {
  registered_name: string;
  representative: string;
  capital: number | null;
  address: string;
  organizations: {
    ubn: string;
    name: string;
    total: number;
    count: number;
    /** 支持過的民國年度 */
    years: number[];
    /** 這個組織全部的裁罰紀錄筆數（不限年份） */
    penalty_count: number;
  }[];
  overview: DonorOverview;
  /** 上市櫃公司自己申報的 ESG（LK-39）；非上市櫃或對不到是 null */
  esg: CompanyEsg | null;
  fields_breakdown: { code: string; label: string; total: number }[];
  donations: {
    id: number;
    donated_on: string | null;
    year: number | null;
    amount: number;
    /** 見 DonationRow.amount_note（LK-49） */
    amount_note: string;
    purpose: string;
    org_ubn: string;
    org_name: string;
    project_name: string;
    source_name: string;
    source_url: string;
  }[];
}

export interface CompanyEsg {
  market: "listed" | "otc";
  market_label: string;
  code: string;
  name: string;
  short_name: string;
  website: string;
  /** 民國年度 */
  report_year: number;
  published_on: string | null;
  scope1: number | null;
  scope1_verified: string;
  scope2: number | null;
  scope2_verified: string;
  scope3: number | null;
  scope3_verified: string;
  /** 百分比數字，例 6.59 */
  renewable_ratio: number | null;
  female_manager_ratio: number | null;
  /** 仟元／人 */
  salary_median: number | null;
  climate_governance: string;
  climate_strategy: string;
  climate_actions: string;
  transition_plan: string;
  climate_targets: string;
  source_name: string;
  source_url: string;
}

export type CategorySource = "official" | "inferred" | "admin";

export interface CategoryTag {
  code: string;
  label: string;
  source: CategorySource;
}

export interface OrgCategories {
  fields: (CategoryTag & { subs: CategoryTag[] })[];
  targets: CategoryTag[];
}

export interface TaxonomyNode {
  code: string;
  label: string;
  count: number;
}

export interface Taxonomy {
  fields: (TaxonomyNode & { subs: TaxonomyNode[] })[];
  targets: TaxonomyNode[];
}

export interface CategoryOverview {
  code: string;
  label: string;
  dimension: "field" | "target";
  parent: { code: string; label: string } | null;
  subs: { code: string; label: string }[];
  since_roc_year: number;
  org_count: number;
  raised_5y: number;
  penalized_5y: number;
  top_level: {
    ubn: string;
    name: string;
    city: string;
    disclosure_level: number;
  }[];
  top_raised: {
    ubn: string;
    name: string;
    city: string;
    disclosure_level: number;
    raised_5y: number;
  }[];
  top_donors: {
    donor_id: number;
    name: string;
    kind_label: string;
    total: number;
    org_count: number;
  }[];
  penalties: {
    id: number;
    decided_on: string | null;
    content: string;
    fine_text: string;
    org_ubn: string;
    org_name: string;
  }[];
  penalty_total: number;
}

/** 首頁探索區（LK-18） */
export interface DiscoverEnding {
  project_id: string;
  name: string;
  end_date: string;
  target: number;
  days_left: number;
  org_ubn: string;
  org_name: string;
  org_level: number;
}

export interface DiscoverPenalty {
  decided_on: string;
  /** 白話的違規類型；歸不進去是空字串 */
  kind: string;
  fine_text: string;
  org_ubn: string;
  org_name: string;
}

export interface DiscoverGift {
  donated_on: string;
  amount: number;
  donor_id: number;
  donor_name: string;
  org_ubn: string;
  org_name: string;
}

export interface Discover {
  ending: DiscoverEnding[];
  penalties: DiscoverPenalty[];
  gifts: DiscoverGift[];
}

/** 首頁領域區（LK-18） */
export interface FieldPickOrg {
  ubn: string;
  name: string;
  city: string;
  level: number;
  raised_5y: number;
  campaign: { project_id: string; name: string; end_date: string; target: number } | null;
}

export interface FieldPicks {
  code: string;
  label: string;
  orgs: FieldPickOrg[];
}
