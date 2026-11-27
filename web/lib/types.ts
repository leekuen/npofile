export type OrgStatus = "active" | "cancelled" | "revoked" | "closed";

export interface OrgSummary {
  ubn: string;
  name: string;
  org_type: string;
  city: string;
  status: OrgStatus;
  status_label: string;
  disclosure_score: number;
  penalty_count_5y: number;
  raised_5y: number;
  tags: CategoryTag[];
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Stats {
  organizations: number;
  with_fundraising: number;
  penalized_5y: number;
  since_roc_year: number;
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
}

export type DonorKind = "company" | "group" | "individual";

export interface DonationRow {
  id: number;
  donor_name: string;
  donor_id: number | null;
  donor_kind: DonorKind | null;
  purpose: string;
  amount: number;
  donated_on: string | null;
  source_name: string;
  source_url: string;
}

export interface ScoreBreakdown {
  basic: number;
  basic_max: number;
  basic_present: Record<
    "ubn" | "org_type" | "address" | "phone" | "website" | "purposes",
    boolean
  >;
  fundraising: number;
  fundraising_max: number;
  project: number;
  project_max: number;
  result: number;
  result_max: number;
  result_funded_projects: number;
  result_filed_projects: number;
  total: number;
}

export interface OrgDetail extends Omit<OrgSummary, "raised_5y"> {
  representative: string;
  registered_address: string;
  contact_address: string;
  phone: string;
  website: string;
  purposes: string;
  source_links: SourceLink[];
  score: ScoreBreakdown;
  annual_records: Annual[];
  projects: Project[];
  penalties: Penalty[];
  donations: DonationRow[];
  corporate_donors: CorporateDonorRank[];
  individual_donors: { name: string; total: number; count: number }[];
  donor_summary: DonorSummary | null;
  since_roc_year: number;
  categories: OrgCategories;
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
}

export interface DonorDetail extends DonorSummaryRow {
  registered_name: string;
  representative: string;
  capital: number | null;
  address: string;
  organizations: { ubn: string; name: string; total: number; count: number }[];
  fields_breakdown: { code: string; label: string; total: number }[];
  donations: {
    id: number;
    donated_on: string | null;
    amount: number;
    purpose: string;
    org_ubn: string;
    org_name: string;
    project_name: string;
    source_name: string;
    source_url: string;
  }[];
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
  top_score: {
    ubn: string;
    name: string;
    city: string;
    disclosure_score: number;
  }[];
  top_raised: {
    ubn: string;
    name: string;
    city: string;
    disclosure_score: number;
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
