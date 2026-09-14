import { FormEvent, useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router-dom";
import ResourcePage from "./api/ResourcePage";
import { CreateRunPage, RunDetailPage, RunsPage } from "./runs/LiveRuns";
import type { ApiPath } from "./api/openapi.generated";

const pages: readonly [string, string, ApiPath][] = [
  ["Home", "/", "/api/v1/system"], ["Targets", "/targets", "/api/v1/targets"],
  ["Workloads", "/workloads", "/api/v1/workloads"], ["Query shapes", "/query-shapes", "/api/v1/query-shapes"],
  ["Runs", "/runs", "/api/v1/runs"], ["Approvals", "/approvals", "/api/v1/approvals"],
  ["Ledger", "/ledger", "/api/v1/ledger"], ["Experience", "/experience", "/api/v1/experience"],
  ["Benchmarks", "/benchmarks", "/api/v1/benchmarks"], ["Settings", "/settings", "/api/v1/settings"],
  ["System", "/system", "/api/v1/system"],
];

function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    const response = await fetch("http://localhost:8000/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
    if (!response.ok) { setError("Login failed."); return; }
    const tokens = await response.json() as { access_token: string; refresh_token: string };
    window.localStorage.setItem("access_token", tokens.access_token); window.localStorage.setItem("refresh_token", tokens.refresh_token); navigate("/");
  }
  return <main className="mx-auto max-w-md p-10"><h1 className="text-3xl font-semibold">Login</h1><form className="mt-6 grid gap-4" onSubmit={submit}><input aria-label="Email" className="rounded border p-2" onChange={(event) => setEmail(event.target.value)} placeholder="Email" required type="email" value={email} /><input aria-label="Password" className="rounded border p-2" minLength={12} onChange={(event) => setPassword(event.target.value)} placeholder="Password" required type="password" value={password} /><button className="rounded bg-blue-700 p-2 text-white" type="submit">Sign in</button>{error && <p className="text-red-700">{error}</p>}</form></main>;
}

export default function App() {
  return <><nav className="border-b border-slate-200 bg-white px-6 py-3 text-sm font-medium"><div className="mx-auto flex max-w-6xl flex-wrap gap-5">{pages.map(([label, to]) => <Link className="text-slate-700 hover:text-blue-700" key={to} to={to}>{label}</Link>)}<Link className="text-slate-700 hover:text-blue-700" to="/login">Login</Link></div></nav><Routes><Route path="/login" element={<Login />} /><Route path="/runs" element={<RunsPage />} /><Route path="/runs/new" element={<CreateRunPage />} /><Route path="/runs/:id" element={<RunDetailPage />} />{pages.filter(([, route]) => route !== "/runs").map(([title, route, path]) => <Route element={<ResourcePage title={title} path={path} />} key={route} path={route} />)}<Route element={<ResourcePage title="Target" path="/api/v1/targets" />} path="/targets/:id" /></Routes></>;
}
