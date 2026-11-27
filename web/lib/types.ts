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
  result_filed_on: string | null;
  closed_filed_on: string | null;
  description: string;
  source_name: string;
  source_url: string;
}

export interface Penalty {
  id: number;
  decided_on: string | null;
  authority: string;
  content: string;
  fine_text: string;
  source_name: string;
  source_url: string;
}

export interface DonationRow {
  id: number;
  donor_name: string;
  amount: number;
  donated_on: string | null;
  source_name: string;
  source_url: string;
}

export interface ScoreBreakdown {
  basic: number;
  basic_max: number;
  basic_present: Record<"ubn" | "org_type" | "address" | "phone" | "website" | "purposes", boolean>;
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

export interface OrgDetail extends OrgSummary {
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
  top_donors: { donor_name: string; total: number }[];
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
