export type ClaimStatus =
  | "queued"
  | "processing"
  | "rejected"
  | "done"
  | "failed"
  | "approved"
  | "declined";

export type CarCategory = "hatchback" | "sedan" | "suv";

export interface Detection {
  damage_type: string;
  part: string;
  confidence: number;
  bbox: [number, number, number, number];
  severity: number;
}

export interface SimilarClaim {
  claim_ref: string;
  damage_type: string;
  part: string;
  car_category: string;
  severity: number;
  cost_pkr: number;
  similarity: number;
  adjusted_cost_pkr: number | null;
}

export interface Assessment {
  detection: Detection;
  image: string;
  similar_claims: SimilarClaim[];
  cost_low_pkr: number;
  cost_high_pkr: number;
  cost_estimate_pkr: number;
  action: "repair" | "replace";
  basis: "retrieval" | "cost_table";
}

export interface QualityResult {
  image: string;
  blur_score: number;
  brightness: number;
  passed: boolean;
  reason: string | null;
}

export interface ClaimResult {
  claim_id: string;
  car_category: CarCategory;
  quality: QualityResult[];
  assessments: Assessment[];
  total_low_pkr: number;
  total_high_pkr: number;
  fraud: { flagged: boolean; reasons: string[] };
  report: string;
  model_versions: Record<string, string>;
  prompt_version: string;
  pipeline_seconds: number;
}

export interface Claim {
  claim_id: string;
  status: ClaimStatus;
  car_category: CarCategory;
  images: string[];
  created_at: string;
  result: ClaimResult | null;
  error: string | null;
  final_cost_pkr: number | null;
}

export interface ClaimSummary {
  claim_id: string;
  status: ClaimStatus;
  car_category: CarCategory;
  created_at: string;
  images: string[];
  damage_count: number;
  total_low_pkr: number | null;
  total_high_pkr: number | null;
  fraud_flagged: boolean;
  final_cost_pkr: number | null;
}

export interface Stats {
  claims_total: number;
  by_status: Record<string, number>;
  fraud_flagged: number;
  avg_pipeline_seconds: number | null;
  index_size: number;
  approved_value_pkr: number;
  damage_mix: Record<string, number>;
  model_versions: Record<string, string>;
}

export interface Drift {
  id: number;
  created_at: string;
  status: "ok" | "drift" | "not_enough_data";
  drift_share: number | null;
  drifted_columns: string[];
  n_reference: number;
  n_current: number;
  has_report: boolean;
  summary: Record<string, number>;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listClaims: (status?: ClaimStatus) =>
    request<ClaimSummary[]>(`/claims${status ? `?status=${status}` : ""}`),
  getClaim: (id: string) => request<Claim>(`/claims/${id}`),
  createClaim: (files: File[], category: CarCategory) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("car_category", category);
    return request<Claim>("/claims", { method: "POST", body: form });
  },
  review: (id: string, approved: boolean, finalCost?: number) =>
    request<Claim>(`/claims/${id}/review`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ approved, final_cost_pkr: finalCost ?? null }),
    }),
  stats: () => request<Stats>("/stats"),
  drift: () => request<Drift | null>("/drift"),
  runDrift: () => request<Drift>("/drift/run", { method: "POST" }),
  driftReportUrl: (id: number, part: "damage" | "photos") => `/api/drift/${id}/report?part=${part}`,
  imageUrl: (id: string, name: string) => `/api/claims/${id}/images/${encodeURIComponent(name)}`,
};
