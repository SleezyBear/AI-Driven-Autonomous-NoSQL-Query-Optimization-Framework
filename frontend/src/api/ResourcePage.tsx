import { useQuery } from "@tanstack/react-query";
import type { ApiPath } from "./openapi.generated";
import { getApi } from "./client";

export default function ResourcePage({ title, path }: { title: string; path: ApiPath }) {
  const query = useQuery({ queryKey: [path], queryFn: () => getApi(path) });
  if (query.isPending) return <main className="mx-auto max-w-6xl p-10">Loading {title}…</main>;
  if (query.isError) return <main className="mx-auto max-w-6xl p-10"><h1 className="text-3xl font-semibold">{title}</h1><p className="mt-4 text-red-700">{query.error.message}. Sign in at /login to view live control-plane data.</p></main>;
  return <main className="mx-auto max-w-6xl p-10"><h1 className="text-3xl font-semibold">{title}</h1><p className="mt-2 text-slate-600">Live control-plane records — no hard-coded dashboard values.</p>{query.data.records.length ? <ul className="mt-6 grid gap-3">{query.data.records.map((record, index) => <li className="rounded-lg border p-4" key={String(record.id ?? index)}><dl className="grid gap-1 text-sm">{Object.entries(record).filter(([key, value]) => !["encrypted_payload", "snapshot", "sanitized_input", "validated_output", "before_state", "after_state", "inverse_action"].includes(key) && value !== null).slice(0, 8).map(([key, value]) => <div key={key}><dt className="inline font-medium text-slate-600">{key.replaceAll("_", " ")}: </dt><dd className="inline">{Array.isArray(value) ? `${value.length} recorded` : typeof value === "object" ? "Recorded" : String(value)}</dd></div>)}</dl></li>)}</ul> : <p className="mt-6 text-slate-600">No records are available.</p>}</main>;
}
