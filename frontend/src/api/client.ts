import type { ApiGetResponses, ApiPath } from "./openapi.generated";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

export type RunSummary = {
  run_id: string; target_id: string; status: string; deployment_mode: string;
  primary_metric_key: string | null; completion_reason: string | null;
  created_at: string; updated_at: string;
};

export type RunDetail = { run: RunSummary; artifacts: Record<string, unknown> };

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const token = window.localStorage.getItem("access_token");
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers },
  });
  if (!response.ok) throw new Error(response.status === 403 ? "You are not authorized for this action." : `API request failed (${response.status})`);
  return response.json();
}

export async function getApi<Path extends ApiPath>(path: Path): Promise<ApiGetResponses[Path]> {
  return request(path) as Promise<ApiGetResponses[Path]>;
}

export async function listRuns(): Promise<RunSummary[]> {
  const page = await request("/api/v1/runs") as { records: RunSummary[] };
  return page.records;
}

export async function getRun(runId: string): Promise<RunDetail> {
  return request(`/api/v1/runs/${encodeURIComponent(runId)}`) as Promise<RunDetail>;
}

export async function createRun(input: Pick<RunSummary, "target_id" | "deployment_mode" | "primary_metric_key">): Promise<RunSummary> {
  return request("/api/v1/runs", { method: "POST", body: JSON.stringify(input) }) as Promise<RunSummary>;
}

export async function decideApproval(id: string, approve: boolean, reason?: string): Promise<void> {
  await request(`/api/v1/approvals/${encodeURIComponent(id)}/${approve ? "approve" : "reject"}`, { method: "POST", body: JSON.stringify({ reason }) });
}
