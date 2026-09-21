import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createRun, decideApproval, getRun, listRuns, type RunDetail, type RunSummary } from "../api/client";

const terminal = new Set(["COMPLETED", "ROLLED_BACK", "ROLLBACK_BLOCKED", "FAILED"]);
const stages = ["CREATED", "SNAPSHOTTING", "DIAGNOSING", "GENERATING_CANDIDATES", "RANKING", "CALIBRATING", "EVALUATING", "ADMISSION", "ADMITTED", "APPROVAL_PENDING", "APPROVED", "DEPLOYING", "DEPLOYED", "MONITORING", "COMPLETED", "ROLLED_BACK", "ROLLBACK_BLOCKED", "FAILED"];

export function runOutcome(run: RunSummary) {
  if (run.status !== "COMPLETED") return run.completion_reason ?? run.status;
  if (run.completion_reason === "NO_CANDIDATES") return "Completed safely: no candidates were generated.";
  if (run.completion_reason === "NO_ADMITTED_CANDIDATE") return "Completed safely: no candidate met admission requirements.";
  if (run.completion_reason === "APPROVAL_REJECTED") return "Completed safely: the approval request was rejected.";
  if (run.completion_reason === "DEPLOYMENT_SUCCEEDED") return "Deployment completed successfully.";
  return run.completion_reason ?? "Deployment completed successfully.";
}

export function RunsPage() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: listRuns });
  if (runs.isPending) return <Page><h1>Runs</h1><p>Loading runs…</p></Page>;
  if (runs.isError) return <Page><h1>Runs</h1><Error error={runs.error} /></Page>;
  if (!runs.data.length) return <Page><h1>Runs</h1><p>No optimization runs have been created.</p><Link to="/runs/new">Create a run</Link></Page>;
  return <Page><div className="flex justify-between"><h1>Runs</h1><Link to="/runs/new">Create run</Link></div><ul className="mt-5 grid gap-3">{runs.data.map((run) => <li className="rounded border p-4" key={run.run_id}><Link to={`/runs/${run.run_id}`}>{run.status}</Link><p className="text-sm text-slate-600">{run.deployment_mode} · {run.primary_metric_key ?? "No primary metric"}</p><p className="text-sm">{runOutcome(run)}</p></li>)}</ul></Page>;
}

export function CreateRunPage() {
  const navigate = useNavigate(); const [targetId, setTargetId] = useState(""); const [mode, setMode] = useState("APPROVAL_CONTROLLED"); const [metric, setMetric] = useState("p99_latency_ms");
  const create = useMutation({ mutationFn: createRun, onSuccess: (run) => navigate(`/runs/${run.run_id}`) });
  function submit(event: FormEvent) { event.preventDefault(); create.mutate({ target_id: targetId, deployment_mode: mode, primary_metric_key: metric || null }); }
  return <Page><h1>Create optimization run</h1><form className="mt-5 grid max-w-lg gap-3" onSubmit={submit}><label>Target ID<input aria-label="Target ID" required value={targetId} onChange={(e) => setTargetId(e.target.value)} /></label><label>Deployment mode<select value={mode} onChange={(e) => setMode(e.target.value)}><option>APPROVAL_CONTROLLED</option><option>FULL_AUTONOMOUS</option></select></label><label>Primary metric<select value={metric} onChange={(e) => setMetric(e.target.value)}><option value="p99_latency_ms">p99 latency</option><option value="p95_latency_ms">p95 latency</option><option value="">None</option></select></label><button disabled={create.isPending} type="submit">{create.isPending ? "Creating…" : "Create run"}</button>{create.isError && <Error error={create.error} />}</form></Page>;
}

export function RunDetailPage() {
  const { id = "" } = useParams(); const query = useQuery({ queryKey: ["run", id], queryFn: () => getRun(id), refetchInterval: (value) => value.state.data && terminal.has(value.state.data.run.status) ? false : 2_000 });
  if (query.isPending) return <Page>Loading run…</Page>; if (query.isError) return <Page><h1>Optimization run</h1><Error error={query.error} /></Page>;
  return <RunDetailView detail={query.data} />;
}

function RunDetailView({ detail }: { detail: RunDetail }) {
  const client = useQueryClient(); const run = detail.run; const artifacts = detail.artifacts as Record<string, Record<string, unknown> | null>; const approval = artifacts.approval;
  const decide = useMutation({ mutationFn: ({ approve }: { approve: boolean }) => decideApproval(String(approval?.id), approve), onSuccess: () => client.invalidateQueries({ queryKey: ["run", run.run_id] }) });
  return <Page><h1>Optimization run</h1><p aria-label="Run status" className="text-lg font-semibold">{run.status}</p><p>{runOutcome(run)}</p><ol aria-label="Lifecycle timeline" className="mt-5 grid gap-1 text-sm">{stages.map((stage, index) => <li key={stage} className={stage === run.status ? "font-bold text-blue-700" : index < stages.indexOf(run.status) ? "text-emerald-700" : "text-slate-500"}>{stage === run.status ? "Current: " : index < stages.indexOf(run.status) ? "Completed: " : "Not reached: "}{stage}</li>)}</ol><section className="mt-6"><h2>Evidence</h2><EvidenceCards artifacts={detail.artifacts} /></section>{run.status === "APPROVAL_PENDING" && typeof approval?.id === "string" && <section className="mt-4"><h2>Approval required</h2><p>{String((artifacts.authority ?? {}).authority_reason ?? "Human approval is required.")}</p><button onClick={() => decide.mutate({ approve: true })} disabled={decide.isPending}>Approve</button><button className="ml-2" onClick={() => decide.mutate({ approve: false })} disabled={decide.isPending}>Reject</button>{decide.isError && <Error error={decide.error} />}</section>}</Page>;
}

function EvidenceCards({ artifacts }: { artifacts: Record<string, unknown> }) {
  const labels: Record<string, string> = { snapshot: "Workload snapshot", diagnosis: "Diagnosis", generation: "Candidate generation", ranking: "Ranking", evaluation_plan: "Evaluation plan", admission: "Admission", authority: "Authority", approval: "Approval", deployment: "Deployment", rollback: "Rollback" };
  return <div className="mt-3 grid gap-3 md:grid-cols-2">{Object.entries(labels).map(([key, label]) => {
    const artifact = artifacts[key];
    if (!artifact || typeof artifact !== "object" || Array.isArray(artifact)) return <article className="rounded border p-4" key={key}><h3>{label}</h3><p className="text-sm text-slate-600">Not recorded for this run.</p></article>;
    const fields = Object.entries(artifact as Record<string, unknown>).filter(([field, value]) => !["id", "created_at", "updated_at", "snapshot", "sanitized_input", "validated_output", "before_state", "after_state", "inverse_action"].includes(field) && value !== null).slice(0, 5);
    return <article className="rounded border p-4" key={key}><h3>{label}</h3>{fields.length ? <dl className="mt-2 grid gap-1 text-sm">{fields.map(([field, value]) => <div key={field}><dt className="inline font-medium text-slate-600">{field.replaceAll("_", " ")}: </dt><dd className="inline">{Array.isArray(value) ? `${value.length} recorded` : typeof value === "object" ? "Recorded" : String(value)}</dd></div>)}</dl> : <p className="text-sm text-slate-600">Recorded; no display-safe summary is available.</p>}</article>;
  })}</div>;
}

function Error({ error }: { error: Error }) { return <p className="text-red-700">{error.message}</p>; }
function Page({ children }: { children: React.ReactNode }) { return <main className="mx-auto max-w-4xl p-6 sm:p-10">{children}</main>; }
