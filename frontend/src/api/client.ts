import type { ApiGetResponses, ApiPath } from "./openapi.generated";

const API_BASE = "http://localhost:8000";

export async function getApi<Path extends ApiPath>(path: Path): Promise<ApiGetResponses[Path]> {
  const token = window.localStorage.getItem("access_token");
  const response = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) throw new Error(`API request failed (${response.status})`);
  return response.json() as Promise<ApiGetResponses[Path]>;
}
