import "server-only";

import type {
  CategoryOverview,
  DonorDetail,
  DonorSummaryRow,
  Filters,
  OrgDetail,
  OrgSummary,
  Page,
  Stats,
  Taxonomy,
} from "./types";

const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8000";

export class ApiUnavailableError extends Error {}

async function get<T>(path: string): Promise<T | null> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
  } catch (e) {
    throw new ApiUnavailableError(`無法連線到後端：${(e as Error).message}`);
  }
  if (res.status === 404) return null;
  if (!res.ok) throw new ApiUnavailableError(`後端回應 ${res.status}`);
  return (await res.json()) as T;
}

export async function getStats() {
  return (await get<Stats>("/api/stats"))!;
}

export async function getFilters() {
  return (await get<Filters>("/api/filters"))!;
}

export interface OrgQuery {
  q?: string;
  city?: string;
  status?: string;
  ordering?: string;
  field?: string;
  sub?: string;
  target?: string;
  page?: string;
}

export async function listOrgs(query: OrgQuery) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v) params.set(k, v);
  const page = await get<Page<OrgSummary>>(`/api/orgs?${params}`);
  // 頁碼超出範圍時 DRF 回 404，當成空結果
  return page ?? { count: 0, next: null, previous: null, results: [] };
}

export async function getOrg(ubn: string) {
  if (!/^\d{8}$/.test(ubn)) return null;
  return get<OrgDetail>(`/api/orgs/${ubn}`);
}

export interface DonorQuery {
  q?: string;
  kind?: string;
  page?: string;
}

export async function listDonors(query: DonorQuery) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v) params.set(k, v);
  const page = await get<Page<DonorSummaryRow>>(`/api/donors?${params}`);
  return page ?? { count: 0, next: null, previous: null, results: [] };
}

export async function getDonor(id: string) {
  if (!/^\d+$/.test(id)) return null;
  return get<DonorDetail>(`/api/donors/${id}`);
}

export async function getTaxonomy() {
  return (await get<Taxonomy>("/api/taxonomy"))!;
}

export async function getCategory(code: string) {
  if (!/^[a-z.]+$/.test(code)) return null;
  return get<CategoryOverview>(`/api/categories/${code}`);
}
