import { useQuery } from "@tanstack/react-query";
import type { ApiPath } from "./openapi.generated";
import { getApi } from "./client";

export default function ResourcePage({ title, path }: { title: string; path: ApiPath }) {
  const query = useQuery({ queryKey: [path], queryFn: () => getApi(path) });
  if (query.isPending) return <main className="mx-auto max-w-6xl p-10">Loading {title}…</main>;
  if (query.isError) return <main className="mx-auto max-w-6xl p-10"><h1 className="text-3xl font-semibold">{title}</h1><p className="mt-4 text-red-700">{query.error.message}. Sign in at /login to view live control-plane data.</p></main>;
  return <main className="mx-auto max-w-6xl p-10"><h1 className="text-3xl font-semibold">{title}</h1><p className="mt-2 text-slate-600">Live control-plane records — no hard-coded dashboard values.</p><pre className="mt-6 overflow-auto rounded-lg bg-slate-950 p-5 text-sm text-slate-100">{JSON.stringify(query.data.records, null, 2)}</pre></main>;
}
